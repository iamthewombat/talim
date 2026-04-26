"""Tests for the risk_check node and rules (WP-17)."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from talim.app.execute_context import configure_execute, get_execute_context
from talim.app.nodes.risk_check import (
    check_signal,
    configure_risk_rules,
    risk_check,
)
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.models.position import Position
from talim.models.signal import Signal
from talim.risk.rules import DEFAULT_RULES, RiskRules, load_rules


def _signal(instrument: str = "ES", side: str = "long") -> Signal:
    return Signal(
        instrument=instrument, strategy="momentum-US500", side=side,
        entry_price=5400.0, stop=5380.0, target=5440.0,
        rationale="t", regime_context="momentum",
    )


def _position(instrument: str = "ES", qty: float = 1.0) -> Position:
    return Position(
        instrument=instrument, side="long", qty=qty,
        entry_price=5400.0, stop=5380.0, target=5440.0,
        strategy="momentum-US500",
    )


def _cfd_signal(
    instrument: str = "AU200.cash",
    *,
    entry_price: float = 9000.0,
    timestamp: datetime | None = None,
) -> Signal:
    return Signal(
        instrument=instrument,
        strategy="momentum-AU200",
        side="long",
        entry_price=entry_price,
        stop=entry_price - 50.0,
        target=entry_price + 75.0,
        rationale="t",
        regime_context="momentum",
        timestamp=timestamp,
    )


def _cfd_position(
    instrument: str = "AU200.cash",
    *,
    qty: float = 1.0,
    entry_price: float = 9000.0,
) -> Position:
    return Position(
        instrument=instrument,
        side="long",
        qty=qty,
        entry_price=entry_price,
        stop=entry_price - 50.0,
        target=entry_price + 75.0,
        strategy="momentum-AU200",
    )


@pytest.fixture(autouse=True)
def _cleanup_execute_context():
    yield
    get_execute_context().reset()


# ---------------------------------------------------------------------------
# Rules loader
# ---------------------------------------------------------------------------

class TestLoadRules:
    def test_default_when_path_none(self):
        assert load_rules(None) is DEFAULT_RULES

    def test_default_when_missing(self, tmp_path):
        assert load_rules(tmp_path / "nope.json") is DEFAULT_RULES

    def test_loads_json(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps({
            "max_position_qty": 2.0,
            "max_total_exposure": 50000.0,
            "correlation_groups": [["ES", "NQ"]],
        }))
        rules = load_rules(path)
        assert rules.max_position_qty == 2.0
        assert rules.max_total_exposure == 50000.0
        assert {"ES", "NQ"} in rules.correlation_groups


# ---------------------------------------------------------------------------
# check_signal — pure function
# ---------------------------------------------------------------------------

class TestCheckSignal:
    def test_passes_within_limits(self):
        rules = RiskRules(
            max_position_qty=5.0,
            max_total_exposure=1_000_000.0,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        )
        ok, reason = check_signal(_signal(), [], 0.0, rules)
        assert ok is True
        assert reason is None

    def test_blocks_oversized_qty(self):
        rules = RiskRules(max_position_qty=2.0)
        ok, reason = check_signal(_signal(), [], 0.0, rules, qty=3.0)
        assert ok is False
        assert "max_position_qty" in reason

    def test_blocks_on_daily_drawdown(self):
        rules = RiskRules(max_daily_drawdown=-1000.0)
        ok, reason = check_signal(_signal(), [], -1500.0, rules)
        assert ok is False
        assert "max_daily_drawdown" in reason

    def test_blocks_on_total_exposure(self):
        rules = RiskRules(
            max_total_exposure=10_000.0,
            block_on_existing_same_instrument=False,
        )
        # Single ES contract @ 5400 = 5400 exposure; pending adds another 5400.
        existing = [_position("NQ", qty=1.0)]
        # NQ @ 5400 = 5400, plus pending 5400 = 10800 > 10000 → blocked.
        ok, reason = check_signal(_signal("ES"), existing, 0.0, rules)
        assert ok is False
        assert "exposure" in reason

    def test_blocks_existing_same_instrument(self):
        rules = RiskRules(block_on_existing_same_instrument=True)
        ok, reason = check_signal(_signal("ES"), [_position("ES")], 0.0, rules)
        assert ok is False
        assert "ES" in reason

    def test_blocks_correlated_when_already_exposed(self):
        # Allow existing same-instrument off so we isolate correlation logic.
        rules = RiskRules(
            block_on_existing_same_instrument=False,
            max_correlated_positions=1,
        )
        # NQ is in the same group as ES.
        ok, reason = check_signal(_signal("ES"), [_position("NQ")], 0.0, rules)
        assert ok is False
        assert "correlated" in reason

    def test_uncorrelated_passes(self):
        rules = RiskRules(
            block_on_existing_same_instrument=False,
            max_correlated_positions=1,
        )
        # GC is not in the equity-index group.
        ok, reason = check_signal(_signal("ES"), [_position("GC")], 0.0, rules)
        assert ok is True

    def test_cfd_margin_limit_blocks(self):
        rules = RiskRules(
            max_total_exposure=1_000_000.0,
            max_margin_utilization_pct=0.5,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        )
        ok, reason = check_signal(
            _cfd_signal(timestamp=datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc)),
            [],
            0.0,
            rules,
            qty=2.0,
            account_balance=1_000.0,
        )
        assert ok is False
        assert "required margin" in reason

    def test_cfd_family_counts_as_correlated(self):
        rules = RiskRules(
            block_on_existing_same_instrument=False,
            max_correlated_positions=1,
            max_total_exposure=1_000_000.0,
        )
        ok, reason = check_signal(
            _cfd_signal(timestamp=datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc)),
            [_cfd_position("AU200.fwd")],
            0.0,
            rules,
        )
        assert ok is False
        assert "correlated" in reason

    def test_cfd_forward_exposure_uses_point_value(self):
        rules = RiskRules(
            max_total_exposure=70_000.0,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        )
        ok, reason = check_signal(
            _cfd_signal("AU200.fwd", timestamp=datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc)),
            [_cfd_position("AU200.cash", qty=3.0)],
            0.0,
            rules,
        )
        assert ok is False
        assert "max_total_exposure" in reason

    def test_cfd_session_window_blocks_when_closed(self):
        closed_time = datetime(2026, 4, 19, 10, 0, tzinfo=ZoneInfo("Australia/Sydney"))
        rules = RiskRules(
            max_total_exposure=1_000_000.0,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        )
        ok, reason = check_signal(
            _cfd_signal(timestamp=closed_time),
            [],
            0.0,
            rules,
        )
        assert ok is False
        assert "session is closed" in reason


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class TestRiskCheckNode:
    def setup_method(self):
        configure_risk_rules(RiskRules(
            max_total_exposure=1_000_000.0,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        ))

    def teardown_method(self):
        configure_risk_rules(RiskRules())

    def test_no_signal_passthrough(self):
        assert risk_check({}) == {}

    def test_passing_signal_returns_empty_update(self):
        update = risk_check({"pending_signal": _signal(), "active_positions": []})
        assert update == {}

    def test_node_reads_daily_pnl_from_state(self):
        # WP-20: risk_check node must read state["daily_pnl"] for the
        # drawdown rule rather than assuming 0.
        configure_risk_rules(RiskRules(max_daily_drawdown=-500.0))
        update = risk_check({
            "pending_signal": _signal(),
            "active_positions": [],
            "daily_pnl": -1000.0,
        })
        assert update["pending_signal"] is None
        assert "max_daily_drawdown" in update["pending_notification"]

    def test_blocked_signal_clears_and_notifies(self):
        configure_risk_rules(RiskRules(
            max_total_exposure=1.0,
            block_on_existing_same_instrument=False,
        ))
        update = risk_check({"pending_signal": _signal(), "active_positions": []})
        assert update["pending_signal"] is None
        assert update["signal_approved"] is False
        assert "Risk check blocked" in update["pending_notification"]

    def test_node_uses_configured_qty_and_balance_for_cfd_margin(self):
        configure_risk_rules(RiskRules(
            max_total_exposure=1_000_000.0,
            max_margin_utilization_pct=0.5,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        ))
        exchange = MockExchange(starting_balance=0.0)
        exchange._balance = {"AUD": 1_000.0}
        configure_execute(exchange, default_qty=2.0)
        update = risk_check({
            "pending_signal": _cfd_signal(
                timestamp=datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc)
            ),
            "active_positions": [],
        })
        assert update["pending_signal"] is None
        assert "required margin" in update["pending_notification"]


# ---------------------------------------------------------------------------
# Graph integration — risk-blocked signal short-circuits the HITL path
# ---------------------------------------------------------------------------

class TestGraphIntegration:
    def test_blocked_signal_routes_through_notify(self):
        from talim.app.entrypoints import cron_trigger

        configure_risk_rules(RiskRules(max_total_exposure=1.0))
        try:
            final = cron_trigger(
                initial_state={"pending_signal": _signal()},  # type: ignore[arg-type]
                thread_id="risk-int-1",
            )
            # Signal cleared, notification was passed through notify.
            assert final.get("pending_signal") is None
            assert final.get("response_message") is not None
            assert "Risk check blocked" in final["response_message"]
        finally:
            configure_risk_rules(RiskRules())
