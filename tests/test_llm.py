"""Tests for the LLM integration layer (WP-13)."""

import pytest

from talim.llm import prompts
from talim.llm.client import LLMClient, LLMResponse, LLMUnavailable
from talim.llm.mock import MockLLMClient


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_strategy_reasoning_includes_fields(self):
        p = prompts.strategy_reasoning_prompt(
            "momentum-US500",
            current_params={"ema_fast_period": 8, "ema_slow_period": 21},
            regime="momentum",
        )
        assert "momentum-US500" in p
        assert "ema_fast_period" in p
        assert "momentum" in p
        assert "JSON" in p

    def test_strategy_reasoning_with_backtest_results(self):
        p = prompts.strategy_reasoning_prompt(
            "momentum-US500",
            current_params={},
            regime="momentum",
            backtest_results=[
                {"param_variant": {"ema_fast_period": 5}, "sharpe_ratio": 1.2,
                 "net_pnl": 100.0, "win_rate": 0.6},
            ],
        )
        assert "variant 1" in p
        assert "sharpe=1.20" in p

    def test_backtest_interpretation(self):
        p = prompts.backtest_interpretation_prompt([
            {"param_variant": {"x": 1}, "sharpe_ratio": 1.5, "net_pnl": 200.0,
             "max_drawdown": -50.0, "total_trades": 12},
        ])
        assert "sharpe=1.50" in p
        assert "drawdown" in p.lower()

    def test_regime_observation(self):
        p = prompts.regime_observation_prompt(
            "momentum",
            fingerprint=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            atr_ratio=1.25,
            prior_regime="mean_reversion",
        )
        assert "momentum" in p
        assert "mean_reversion" in p
        assert "1.25" in p

    def test_regime_observation_no_prior(self):
        p = prompts.regime_observation_prompt(
            "high_vol", fingerprint=[1.0] * 6, atr_ratio=2.0,
        )
        # No 'previous regime' clause
        assert "Previous regime" not in p
        assert "high_vol" in p

    def test_message_classification(self):
        p = prompts.message_classification_prompt("what's my P&L?")
        assert "QUESTION" in p
        assert "BACKTEST" in p
        assert "what's my P&L?" in p


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------

class TestMockClient:
    def test_canned_responses(self):
        m = MockLLMClient(responses=["first", "second"])
        assert m.reason("p1").text == "first"
        assert m.reason("p2").text == "second"
        # Default fallthrough once exhausted.
        assert "[mock" in m.reason("p3").text

    def test_responder_callback(self):
        m = MockLLMClient(responder=lambda method, prompt: f"{method}:{len(prompt)}")
        r = m.reason("hello")
        assert r.text == "reason:5"
        c = m.classify("xx")
        assert c.text == "classify:2"

    def test_records_calls(self):
        m = MockLLMClient()
        m.reason("a")
        m.classify("b")
        assert m.calls == [("reason", "a"), ("classify", "b")]

    def test_context_included_in_record(self):
        m = MockLLMClient()
        m.reason("p", context={"k": "v"})
        method, captured = m.calls[0]
        assert method == "reason"
        assert "k" in captured and "v" in captured

    def test_unavailable_raises(self):
        m = MockLLMClient(unavailable=True)
        with pytest.raises(LLMUnavailable):
            m.reason("anything")
        with pytest.raises(LLMUnavailable):
            m.classify("anything")

    def test_response_shape(self):
        m = MockLLMClient(responses=["ok"])
        r = m.reason("p")
        assert isinstance(r, LLMResponse)
        assert r.backend == "mock"


# ---------------------------------------------------------------------------
# Real LLMClient — covers fallback / missing-config paths without network
# ---------------------------------------------------------------------------

class TestLLMClientFallback:
    def test_reason_without_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = LLMClient(anthropic_api_key=None)
        with pytest.raises(LLMUnavailable):
            client.reason("hi")

    def test_classify_falls_back_to_claude(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Point Ollama at an unreachable URL so the first attempt fails fast.
        client = LLMClient(
            anthropic_api_key=None,
            ollama_url="http://127.0.0.1:1",
            request_timeout=0.5,
        )
        # Both backends unavailable → wrapped LLMUnavailable.
        with pytest.raises(LLMUnavailable):
            client.classify("classify me")

    def test_classify_uses_claude_when_ollama_down(self, monkeypatch):
        # Stub the reason() method to verify the fallback path is taken.
        client = LLMClient(
            anthropic_api_key="fake",
            ollama_url="http://127.0.0.1:1",
            request_timeout=0.5,
        )
        called = {}

        def fake_reason(prompt, context=None):
            called["yes"] = prompt
            return LLMResponse(text="claude-out", backend="claude", model="x", metadata={})

        client.reason = fake_reason  # type: ignore[method-assign]
        out = client.classify("hello")
        assert out.text == "claude-out"
        assert called["yes"] == "hello"
