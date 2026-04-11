"""Tests for the LLM-powered nodes: converse, strategy_update, notify (WP-14)."""

import pytest

from talim.app.entrypoints import bridge_message
from talim.app.llm_context import configure_llm_client, reset_llm_client
from talim.app.nodes.converse import converse, _find_strategy_references
from talim.app.nodes.notify import notify
from talim.app.nodes.strategy_update import strategy_update, _parse_json_proposal
from talim.llm.mock import MockLLMClient
from talim.models.backtest import BacktestResult


@pytest.fixture(autouse=True)
def _reset_llm():
    reset_llm_client()
    yield
    reset_llm_client()


# ---------------------------------------------------------------------------
# strategy_update
# ---------------------------------------------------------------------------

class TestStrategyUpdate:
    def test_no_client_returns_safe_default(self):
        update = strategy_update({"regime": "momentum"})
        assert update == {"regime_changed": False}

    def test_proposes_param_change(self):
        client = MockLLMClient(responses=[
            '{"ema_fast_period": 5, "rationale": "tighter trigger for momentum"}'
        ])
        configure_llm_client(client)

        update = strategy_update({
            "regime": "momentum",
            "active_strategies": ["momentum-ES"],
            "strategy_params": {"momentum-ES": {"ema_fast_period": 8, "ema_slow_period": 21}},
        })

        assert update["regime_changed"] is False
        assert update["strategy_params"]["momentum-ES"]["ema_fast_period"] == 5
        assert update["strategy_params"]["momentum-ES"]["ema_slow_period"] == 21
        assert "tighter trigger" in update["pending_notification"]

    def test_unparseable_response_does_not_crash(self):
        client = MockLLMClient(responses=["the model went off the rails"])
        configure_llm_client(client)

        update = strategy_update({
            "regime": "momentum",
            "active_strategies": ["momentum-ES"],
        })
        assert "pending_notification" in update
        assert "(no change)" in update["pending_notification"]

    def test_parse_json_proposal(self):
        assert _parse_json_proposal('{"a": 1}') == {"a": 1}
        assert _parse_json_proposal('text {"a": 2} more') == {"a": 2}
        assert _parse_json_proposal("no json here") is None
        assert _parse_json_proposal("") is None

    def test_llm_unavailable_returns_safe_default(self):
        configure_llm_client(MockLLMClient(unavailable=True))
        update = strategy_update({
            "regime": "momentum",
            "active_strategies": ["momentum-ES"],
        })
        assert update == {"regime_changed": False}


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------

class TestNotify:
    def _backtest(self) -> list[BacktestResult]:
        return [BacktestResult(
            strategy_name="momentum-ES",
            net_pnl=200.0,
            sharpe_ratio=1.5,
            max_drawdown=-50.0,
            win_rate=0.6,
            total_trades=10,
            param_variant={"ema_fast_period": 8},
        )]

    def test_formats_backtest_without_llm(self):
        update = notify({"backtest_result": self._backtest()})
        msg = update["response_message"]
        assert "momentum-ES" in msg
        assert "sharpe=1.50" in msg
        assert update["pending_notification"] is None

    def test_formats_backtest_with_llm(self):
        configure_llm_client(MockLLMClient(responses=["LLM-summarised backtest"]))
        update = notify({"backtest_result": self._backtest()})
        assert update["response_message"] == "LLM-summarised backtest"

    def test_passes_through_pending_notification(self):
        update = notify({"pending_notification": "Strategy updated: ema=5"})
        assert update["response_message"] == "Strategy updated: ema=5"
        assert update["pending_notification"] is None

    def test_user_message_without_llm(self):
        update = notify({"last_user_message": "what's up?"})
        assert update["response_message"] == "ack"
        assert update["last_user_message"] is None

    def test_user_message_with_llm(self):
        configure_llm_client(MockLLMClient(responses=["You are flat with no positions."]))
        update = notify({"last_user_message": "what's my P&L?"})
        assert "flat" in update["response_message"]
        assert update["last_user_message"] is None


# ---------------------------------------------------------------------------
# converse
# ---------------------------------------------------------------------------

class TestConverse:
    def test_finds_strategy_reference(self):
        refs = _find_strategy_references(
            "what does momentum-ES think?", ["momentum-ES", "mean-reversion-ES"]
        )
        assert refs == ["momentum-ES"]

    def test_finds_multiple_strategies(self):
        refs = _find_strategy_references(
            "compare Momentum-ES and mean-reversion-ES",
            ["momentum-ES", "mean-reversion-ES"],
        )
        assert set(refs) == {"momentum-ES", "mean-reversion-ES"}

    def test_no_strategies_no_active_field(self):
        update = converse({"last_user_message": "hello there"})
        # No known strategies referenced → no active_strategies update.
        assert "active_strategies" not in update

    def test_loads_referenced_strategy_into_active(self):
        update = converse({"last_user_message": "what does momentum-ES think?"})
        assert "momentum-ES" in update.get("active_strategies", [])

    def test_empty_message_noop(self):
        assert converse({}) == {}

    def test_classifier_called_when_client_present(self):
        client = MockLLMClient(responses=["QUESTION"])
        configure_llm_client(client)
        converse({"last_user_message": "what's my P&L?"})
        assert any(c[0] == "classify" for c in client.calls)


# ---------------------------------------------------------------------------
# Graph integration
# ---------------------------------------------------------------------------

class TestBridgePathIntegration:
    def test_converse_router_notify_with_user_question(self):
        configure_llm_client(MockLLMClient(responses=["QUESTION", "Your P&L is +$200."]))
        final = bridge_message("what's my P&L?", thread_id="bridge-llm-1")
        assert final.get("response_message") == "Your P&L is +$200."
        assert final.get("last_user_message") is None
