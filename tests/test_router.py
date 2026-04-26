"""Tests for the router node and conditional edges (WP-10)."""

from talim.app.edges import route_from_router, ROUTER_BRANCHES
from talim.app.nodes.router import router
from talim.models.signal import Signal
from talim.models.backtest import BacktestRequest


def _signal() -> Signal:
    return Signal(
        instrument="ES", strategy="momentum-US500", side="long",
        entry_price=5400.0, stop=5380.0, target=5440.0,
        rationale="t", regime_context="momentum",
    )


class TestRouterNode:
    def test_router_is_noop(self):
        assert router({}) == {}

    def test_router_does_not_mutate_state(self):
        state = {"pending_signal": _signal()}
        result = router(state)
        assert result == {}
        assert state.get("pending_signal") is not None


class TestRouteFromRouter:
    def test_pending_signal_routes_to_risk_check(self):
        assert route_from_router({"pending_signal": _signal()}) == "risk_check"

    def test_regime_changed_routes_to_strategy_update(self):
        assert route_from_router({"regime_changed": True}) == "strategy_update"

    def test_pending_backtest_routes_to_backtest_run(self):
        state = {"pending_backtest": BacktestRequest(strategy_name="momentum-US500")}
        assert route_from_router(state) == "backtest_run"

    def test_user_message_routes_to_notify(self):
        assert route_from_router({"last_user_message": "hi"}) == "notify"

    def test_empty_routes_to_end(self):
        assert route_from_router({}) == "end"

    def test_regime_changed_false_routes_to_end(self):
        assert route_from_router({"regime_changed": False}) == "end"


class TestPriority:
    def test_signal_beats_regime(self):
        state = {"pending_signal": _signal(), "regime_changed": True}
        assert route_from_router(state) == "risk_check"

    def test_signal_beats_backtest(self):
        state = {
            "pending_signal": _signal(),
            "pending_backtest": BacktestRequest(strategy_name="momentum-US500"),
        }
        assert route_from_router(state) == "risk_check"

    def test_regime_beats_backtest(self):
        state = {
            "regime_changed": True,
            "pending_backtest": BacktestRequest(strategy_name="momentum-US500"),
        }
        assert route_from_router(state) == "strategy_update"

    def test_backtest_beats_user_message(self):
        state = {
            "pending_backtest": BacktestRequest(strategy_name="momentum-US500"),
            "last_user_message": "hi",
        }
        assert route_from_router(state) == "backtest_run"


class TestBranchesContract:
    def test_all_branches_listed(self):
        assert set(ROUTER_BRANCHES) == {
            "risk_check", "strategy_update", "backtest_run", "notify", "end",
        }
