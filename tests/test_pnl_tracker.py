"""Tests for the P&L tracker (WP-36)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from talim.connectors.exchange.mock_exchange import MockExchange
from talim.models.position import Position
from talim.risk.pnl_tracker import PnLTracker, PnLSnapshot


class _StaticExchange:
    def __init__(self, *, balances: dict[str, float], positions: list[Position]) -> None:
        self._balances = balances
        self._positions = positions

    def get_account_balance(self) -> dict[str, float]:
        return dict(self._balances)

    def get_positions(self) -> list[Position]:
        return list(self._positions)


def _exchange_with_position() -> MockExchange:
    ex = MockExchange(starting_balance=100_000.0)
    ex.set_fill_price("ES", 5000.0)
    ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")
    return ex


class TestPnLSnapshot:
    def test_to_dict(self):
        snap = PnLSnapshot(
            open_pnl=100.0,
            daily_pnl=50.0,
            account_balance=100_050.0,
            position_count=1,
            timestamp="2025-06-15T10:00:00+00:00",
        )
        d = snap.to_dict()
        assert d["open_pnl"] == 100.0
        assert d["daily_pnl"] == 50.0
        assert d["position_count"] == 1
        assert d["account_currency"] == ""


class TestPnLTracker:
    def test_initial_refresh(self):
        ex = MockExchange(starting_balance=100_000.0)
        tracker = PnLTracker()
        snap = tracker.refresh(ex)

        assert snap.account_balance == 100_000.0
        assert snap.daily_pnl == 0.0
        assert snap.open_pnl == 0.0
        assert snap.position_count == 0

    def test_refresh_with_position(self):
        ex = _exchange_with_position()
        tracker = PnLTracker()
        snap = tracker.refresh(ex)

        assert snap.position_count == 1
        # Balance changed because of the fill (buy 1 @ 5000 = -5000 from USD)
        assert snap.account_balance == 100_000.0 - 5000.0

    def test_daily_pnl_tracks_balance_change(self):
        ex = MockExchange(starting_balance=100_000.0)
        tracker = PnLTracker()

        # First refresh: baseline
        tracker.refresh(ex)

        # Simulate a fill that changes balance
        ex.set_fill_price("ES", 5000.0)
        ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")

        snap2 = tracker.refresh(ex)
        # Balance dropped by 5000 (bought 1 @ 5000)
        assert snap2.daily_pnl == -5000.0

    def test_daily_pnl_accumulates(self):
        ex = MockExchange(starting_balance=100_000.0)
        tracker = PnLTracker()
        tracker.refresh(ex)

        # Trade 1
        ex.set_fill_price("ES", 5000.0)
        ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")
        tracker.refresh(ex)

        # Trade 2: sell to close (balance goes back up)
        ex.set_fill_price("ES", 5010.0)
        ex.place_order("ES", "sell", 1.0, strategy="momentum-US500")
        snap = tracker.refresh(ex)

        # Net effect: bought at 5000, sold at 5010 → +10 realised
        # daily_pnl = (-5000) + (5010) = +10
        assert abs(snap.daily_pnl - 10.0) < 0.01

    def test_reset_daily_zeroes(self):
        ex = MockExchange(starting_balance=100_000.0)
        tracker = PnLTracker()
        tracker.refresh(ex)

        ex.set_fill_price("ES", 5000.0)
        ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")
        tracker.refresh(ex)
        assert tracker._daily_pnl != 0.0

        tracker.reset_daily()
        assert tracker._daily_pnl == 0.0
        assert tracker._last_balance is None

    def test_session_rollover_resets_daily(self):
        ex = MockExchange(starting_balance=100_000.0)
        tracker = PnLTracker()

        # First refresh sets the session date
        tracker.refresh(ex)

        ex.set_fill_price("ES", 5000.0)
        ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")
        tracker.refresh(ex)
        assert tracker._daily_pnl != 0.0

        # Simulate date change by modifying session date
        tracker._session_date = "2025-06-14"  # yesterday
        snap = tracker.refresh(ex)
        # After rollover, daily_pnl resets, then no balance change → 0
        assert snap.daily_pnl == 0.0

    def test_open_pnl_sums_positions(self):
        ex = MockExchange(starting_balance=100_000.0)
        # Manually set open_pnl on a position
        ex.set_fill_price("ES", 5000.0)
        ex.place_order("ES", "buy", 1.0, strategy="momentum-US500")
        # MockExchange doesn't update open_pnl on its own,
        # so set it directly for this test
        pos = ex.get_positions()[0]
        pos.open_pnl = 150.0

        tracker = PnLTracker()
        snap = tracker.refresh(ex)
        assert snap.open_pnl == 150.0

    def test_custom_timezone(self):
        from datetime import timedelta
        est = timezone(timedelta(hours=-5))
        tracker = PnLTracker(session_tz=est)
        ex = MockExchange(starting_balance=50_000.0)
        snap = tracker.refresh(ex)
        assert "-05:00" in snap.timestamp
        assert snap.account_balance == 50_000.0

    def test_prefers_cfd_quote_currency_when_multiple_balances_present(self):
        position = Position(
            instrument="AU200.cash",
            side="long",
            qty=1.0,
            entry_price=9000.0,
            stop=8950.0,
            target=9075.0,
            strategy="momentum-AU200",
            open_pnl=125.0,
        )
        exchange = _StaticExchange(
            balances={"USD": 10_000.0, "AUD": 15_000.0},
            positions=[position],
        )
        tracker = PnLTracker()
        snap = tracker.refresh(exchange, now=datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc))

        assert snap.account_currency == "AUD"
        assert snap.account_balance == 15_000.0
        assert snap.open_pnl == 125.0

    def test_estimates_financing_for_overnight_cash_cfd(self):
        now = datetime(2026, 4, 15, 2, 0, tzinfo=timezone.utc)
        entry_time = now - timedelta(days=2)
        position = Position(
            instrument="AU200.cash",
            side="long",
            qty=1.0,
            entry_price=9000.0,
            stop=8950.0,
            target=9075.0,
            strategy="momentum-AU200",
            open_pnl=100.0,
            entry_time=entry_time,
        )
        exchange = _StaticExchange(
            balances={"AUD": 100_000.0},
            positions=[position],
        )
        tracker = PnLTracker(
            session_tz=ZoneInfo("Australia/Sydney"),
            financing_annual_rate=0.10,
        )
        snap = tracker.refresh(exchange, now=now)

        expected_financing = 9000.0 * 0.10 / 365.0 * 2
        assert snap.gross_open_pnl == 100.0
        assert snap.financing_cost == expected_financing
        assert snap.open_pnl == snap.gross_open_pnl - expected_financing
        assert snap.margin_in_use == 450.0
