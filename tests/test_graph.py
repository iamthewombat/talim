"""Integration tests for the LangGraph skeleton."""

from talim.app.graph import build_graph, route_after_risk, route_from_router
from talim.app.entrypoints import cron_trigger, bridge_message
from talim.app.checkpointer import create_checkpointer
from talim.models.signal import Signal
from talim.models.backtest import BacktestRequest


# ---------------------------------------------------------------------------
# Graph build + routing
# ---------------------------------------------------------------------------

class TestGraphBuild:
    def test_build_graph_compiles(self):
        graph = build_graph()
        assert graph is not None

    def test_build_with_checkpointer(self):
        cp = create_checkpointer(":memory:")
        graph = build_graph(checkpointer=cp)
        assert graph is not None


class TestRouterBranching:
    def test_pending_signal_routes_to_risk_check(self):
        state = {"pending_signal": Signal(
            instrument="ES", strategy="momentum-US500", side="long",
            entry_price=5400.0, stop=5380.0, target=5440.0,
            rationale="test", regime_context="momentum",
        )}
        assert route_from_router(state) == "risk_check"

    def test_regime_changed_routes_to_strategy_update(self):
        state = {"regime_changed": True}
        assert route_from_router(state) == "strategy_update"

    def test_pending_backtest_routes_to_backtest_run(self):
        state = {"pending_backtest": BacktestRequest(strategy_name="momentum-US500")}
        assert route_from_router(state) == "backtest_run"

    def test_user_message_routes_to_notify(self):
        state = {"last_user_message": "what's my P&L?"}
        assert route_from_router(state) == "notify"

    def test_empty_state_routes_to_end(self):
        assert route_from_router({}) == "end"

    def test_signal_takes_priority_over_regime(self):
        state = {
            "pending_signal": Signal(
                instrument="ES", strategy="momentum-US500", side="long",
                entry_price=5400.0, stop=5380.0, target=5440.0,
                rationale="", regime_context="",
            ),
            "regime_changed": True,
        }
        assert route_from_router(state) == "risk_check"

    def test_entry_signal_routes_to_hitl_after_risk(self):
        state = {"pending_signal": Signal(
            instrument="ES", strategy="momentum-US500", side="long",
            entry_price=5400.0, stop=5380.0, target=5440.0,
            rationale="test", regime_context="momentum",
        )}
        assert route_after_risk(state) == "hitl_interrupt"

    def test_exit_signal_routes_to_execute_after_risk(self):
        state = {"pending_signal": Signal(
            instrument="ES", strategy="momentum-US500", side="long",
            entry_price=5380.0, stop=0.0, target=0.0,
            rationale="stop hit", regime_context="", action="exit",
        )}
        assert route_after_risk(state) == "execute"

    def test_risk_block_routes_to_notify_after_risk(self):
        assert route_after_risk({"pending_notification": "blocked"}) == "notify"


# ---------------------------------------------------------------------------
# Cron path
# ---------------------------------------------------------------------------

class TestCronPath:
    def test_cron_trigger_runs_to_end(self):
        final = cron_trigger(thread_id="cron-test-1")
        # Empty state → signal_scanner → router → END
        assert final is not None
        assert final.get("thread_id") == "cron-test-1"
        assert final.get("last_scan_time") is not None

    def test_cron_with_regime_change(self):
        initial = {"regime_changed": True}
        final = cron_trigger(
            initial_state=initial, thread_id="cron-test-2"  # type: ignore[arg-type]
        )
        # Routes to strategy_update → notify → END
        # strategy_update stub clears regime_changed
        assert final.get("regime_changed") is False

    def test_cron_with_pending_backtest(self):
        initial = {"pending_backtest": BacktestRequest(strategy_name="momentum-US500")}
        final = cron_trigger(
            initial_state=initial, thread_id="cron-test-3"  # type: ignore[arg-type]
        )
        # backtest_run stub clears pending_backtest
        assert final.get("pending_backtest") is None


# ---------------------------------------------------------------------------
# Bridge path
# ---------------------------------------------------------------------------

class TestBridgePath:
    def test_bridge_message_runs_to_end(self):
        final = bridge_message(
            message="what's my P&L?", thread_id="bridge-test-1"
        )
        # converse → router → notify → END
        assert final is not None
        # notify stub clears last_user_message and sets response
        assert final.get("response_message") == "ack"
        assert final.get("last_user_message") is None


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------

class TestCheckpointing:
    def test_checkpoint_persists_state(self, tmp_path):
        db_path = str(tmp_path / "chk.db")
        cp1 = create_checkpointer(db_path)
        graph1 = build_graph(checkpointer=cp1)

        config = {"configurable": {"thread_id": "persist-1"}}
        initial = {"thread_id": "persist-1", "last_scan_time": "2025-06-15T09:30:00"}
        graph1.invoke(initial, config=config)

        # New process: new checkpointer + graph with the same DB
        cp2 = create_checkpointer(db_path)
        graph2 = build_graph(checkpointer=cp2)
        snapshot = graph2.get_state(config)
        assert snapshot is not None
        assert snapshot.values.get("thread_id") == "persist-1"
