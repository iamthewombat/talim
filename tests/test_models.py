"""Unit tests for Talim core data models."""

from datetime import datetime, date

from talim.models import (
    OHLCVBar,
    Position,
    Signal,
    BacktestRequest,
    BacktestResult,
    TalimState,
    TALIM_STATE_FIELDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bar() -> OHLCVBar:
    return OHLCVBar(
        instrument="ES",
        timestamp=datetime(2025, 6, 15, 9, 30, 0),
        open=5400.0,
        high=5410.0,
        low=5395.0,
        close=5405.0,
        volume=12000.0,
        timeframe="5m",
    )


def _make_position() -> Position:
    return Position(
        instrument="ES",
        side="long",
        qty=2.0,
        entry_price=5400.0,
        stop=5380.0,
        target=5440.0,
        strategy="momentum-ES",
        open_pnl=200.0,
        entry_time=datetime(2025, 6, 15, 9, 35, 0),
        position_id="pos-001",
    )


def _make_signal() -> Signal:
    return Signal(
        instrument="ES",
        strategy="momentum-ES",
        side="long",
        entry_price=5400.0,
        stop=5380.0,
        target=5440.0,
        rationale="EMA crossover with strong momentum",
        regime_context="momentum",
        timestamp=datetime(2025, 6, 15, 9, 30, 0),
        confidence=0.85,
    )


def _make_backtest_request() -> BacktestRequest:
    return BacktestRequest(
        strategy_name="momentum-ES",
        instrument="AU200.cash",
        timeframe="1h",
        param_variants=[{"ema_fast": 8, "ema_slow": 21}],
        matched_dates=[date(2025, 3, 10), date(2025, 4, 22)],
        data_dir="data/es",
    )


def _make_backtest_result() -> BacktestResult:
    return BacktestResult(
        strategy_name="momentum-ES",
        net_pnl=1250.0,
        sharpe_ratio=1.8,
        max_drawdown=-400.0,
        win_rate=0.62,
        total_trades=50,
        param_variant={"ema_fast": 8, "ema_slow": 21},
        matched_dates=[date(2025, 3, 10), date(2025, 4, 22)],
    )


# ---------------------------------------------------------------------------
# Instantiation tests
# ---------------------------------------------------------------------------

class TestOHLCVBar:
    def test_instantiation(self):
        bar = _make_bar()
        assert bar.instrument == "ES"
        assert bar.close == 5405.0
        assert bar.timeframe == "5m"

    def test_roundtrip(self):
        bar = _make_bar()
        d = bar.to_dict()
        restored = OHLCVBar.from_dict(d)
        assert restored == bar

    def test_to_dict_timestamp_is_string(self):
        bar = _make_bar()
        d = bar.to_dict()
        assert isinstance(d["timestamp"], str)

    def test_immutable(self):
        bar = _make_bar()
        try:
            bar.close = 9999.0  # type: ignore
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestPosition:
    def test_instantiation(self):
        pos = _make_position()
        assert pos.instrument == "ES"
        assert pos.side == "long"
        assert pos.open_pnl == 200.0

    def test_roundtrip(self):
        pos = _make_position()
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.instrument == pos.instrument
        assert restored.entry_price == pos.entry_price
        assert restored.entry_time == pos.entry_time

    def test_roundtrip_no_entry_time(self):
        pos = Position(
            instrument="NQ",
            side="short",
            qty=1.0,
            entry_price=18000.0,
            stop=18100.0,
            target=17800.0,
            strategy="mean-reversion-NQ",
        )
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.entry_time is None


class TestSignal:
    def test_instantiation(self):
        sig = _make_signal()
        assert sig.strategy == "momentum-ES"
        assert sig.confidence == 0.85

    def test_roundtrip(self):
        sig = _make_signal()
        d = sig.to_dict()
        restored = Signal.from_dict(d)
        assert restored == sig

    def test_roundtrip_no_timestamp(self):
        sig = Signal(
            instrument="ES",
            strategy="momentum-ES",
            side="long",
            entry_price=5400.0,
            stop=5380.0,
            target=5440.0,
            rationale="test",
            regime_context="momentum",
        )
        d = sig.to_dict()
        restored = Signal.from_dict(d)
        assert restored == sig
        assert restored.timestamp is None


class TestBacktestRequest:
    def test_instantiation(self):
        req = _make_backtest_request()
        assert req.strategy_name == "momentum-ES"
        assert req.instrument == "AU200.cash"
        assert req.timeframe == "1h"
        assert len(req.matched_dates) == 2

    def test_roundtrip(self):
        req = _make_backtest_request()
        d = req.to_dict()
        restored = BacktestRequest.from_dict(d)
        assert restored.strategy_name == req.strategy_name
        assert restored.instrument == req.instrument
        assert restored.timeframe == req.timeframe
        assert restored.matched_dates == req.matched_dates
        assert restored.param_variants == req.param_variants


class TestBacktestResult:
    def test_instantiation(self):
        res = _make_backtest_result()
        assert res.sharpe_ratio == 1.8
        assert res.total_trades == 50

    def test_roundtrip(self):
        res = _make_backtest_result()
        d = res.to_dict()
        restored = BacktestResult.from_dict(d)
        assert restored.strategy_name == res.strategy_name
        assert restored.net_pnl == res.net_pnl
        assert restored.matched_dates == res.matched_dates


# ---------------------------------------------------------------------------
# TalimState completeness
# ---------------------------------------------------------------------------

class TestTalimState:
    EXPECTED_FIELDS = {
        # Market data
        "current_bar",
        "last_tick",
        "instrument",
        "atr_current",
        "atr_ratio",
        # Regime
        "regime",
        "regime_fingerprint",
        "regime_changed",
        # Signals & trading
        "pending_signal",
        "signal_approved",
        "active_positions",
        "open_pnl",
        "daily_pnl",
        "last_action",
        # Strategy
        "active_strategies",
        "strategy_params",
        # Backtest
        "pending_backtest",
        "backtest_result",
        # Conversation
        "last_user_message",
        "response_message",
        "discord_thread_id",
        "messages",
        # Notifications
        "pending_notification",
        # Meta
        "thread_id",
        "last_scan_time",
        "halted",
    }

    def test_all_expected_fields_present(self):
        missing = self.EXPECTED_FIELDS - TALIM_STATE_FIELDS
        assert not missing, f"Missing fields in TalimState: {missing}"

    def test_no_unexpected_fields(self):
        extra = TALIM_STATE_FIELDS - self.EXPECTED_FIELDS
        assert not extra, f"Unexpected fields in TalimState: {extra}"

    def test_can_create_minimal_state(self):
        state: TalimState = {"thread_id": "test-001"}  # type: ignore
        assert state["thread_id"] == "test-001"

    def test_can_create_full_state(self):
        state: TalimState = {
            "current_bar": _make_bar(),
            "atr_current": 12.5,
            "atr_ratio": 1.2,
            "regime": "momentum",
            "regime_fingerprint": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "regime_changed": False,
            "pending_signal": _make_signal(),
            "signal_approved": None,
            "active_positions": [_make_position()],
            "active_strategies": ["momentum-ES"],
            "strategy_params": {"momentum-ES": {"ema_fast": 8, "ema_slow": 21}},
            "pending_backtest": None,
            "backtest_result": None,
            "last_user_message": None,
            "response_message": None,
            "pending_notification": None,
            "thread_id": "test-001",
            "last_scan_time": None,
        }
        assert state["regime"] == "momentum"
        assert len(state["active_positions"]) == 1
