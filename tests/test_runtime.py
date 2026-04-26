"""Tests for the live runtime bootstrap layer (WP-62)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from talim.api.bridge import create_app
from talim.app.execute_context import get_execute_context
from talim.app.nodes.risk_check import get_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.app.runtime import RuntimeConfig, RuntimeConfigError, bootstrap_runtime
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.risk.rules import RiskRules


@pytest.fixture(autouse=True)
def _reset_runtime_contexts():
    yield
    scanner_context.reset()
    get_execute_context().reset()
    from talim.app.nodes.risk_check import configure_risk_rules

    configure_risk_rules(RiskRules())


def _set_runtime_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TALIM_CHECKPOINT_DB", str(tmp_path / "state" / "checkpoints.db"))
    monkeypatch.setenv("TALIM_EPISODIC_DB", str(tmp_path / "state" / "episodic.db"))
    monkeypatch.setenv("TALIM_RISK_CONFIG", "config/risk.json")


def test_runtime_config_defaults_to_safe_mock(monkeypatch, tmp_path):
    monkeypatch.delenv("TALIM_EXCHANGE_MODE", raising=False)
    monkeypatch.delenv("TALIM_EXCHANGE_NAME", raising=False)
    monkeypatch.delenv("TALIM_INSTRUMENTS", raising=False)
    monkeypatch.delenv("TALIM_STRATEGIES", raising=False)
    _set_runtime_paths(monkeypatch, tmp_path)

    config = RuntimeConfig.from_env()

    assert config.exchange_mode == "mock"
    assert config.exchange_name is None
    assert config.instruments == ()
    assert config.strategies == ()


def test_runtime_config_requires_explicit_live_strategy_and_instrument(monkeypatch, tmp_path):
    _set_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "testnet")
    monkeypatch.setenv("TALIM_EXCHANGE_NAME", "ig")
    monkeypatch.delenv("TALIM_INSTRUMENTS", raising=False)
    monkeypatch.delenv("TALIM_STRATEGIES", raising=False)

    try:
        RuntimeConfig.from_env()
    except RuntimeConfigError as e:
        assert "TALIM_INSTRUMENTS" in str(e)
        assert "TALIM_STRATEGIES" in str(e)
    else:
        raise AssertionError("expected RuntimeConfigError")


def test_bootstrap_runtime_wires_contexts(monkeypatch, tmp_path):
    _set_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
    monkeypatch.setenv("TALIM_PRICEFEED", "mock")
    monkeypatch.setenv("TALIM_INSTRUMENTS", "ES,NQ")
    monkeypatch.setenv("TALIM_STRATEGIES", "momentum-US500")
    monkeypatch.setenv("TALIM_DEFAULT_QTY", "2")
    monkeypatch.setenv("TALIM_BAR_WINDOW", "25")

    runtime = bootstrap_runtime()

    assert isinstance(runtime.exchange, MockExchange)
    assert isinstance(runtime.price_feed, MockPriceFeed)
    assert runtime.price_feed.subscriptions == {"ES", "NQ"}
    assert [strategy.name for strategy in runtime.strategies] == ["momentum-US500"]
    assert scanner_context.price_feed is runtime.price_feed
    assert scanner_context.bar_window == 25
    assert set(scanner_context.strategies) == {"momentum-US500"}
    assert get_execute_context().exchange is runtime.exchange
    assert get_execute_context().default_qty == 2
    assert get_risk_rules().max_position_qty == 5.0
    assert (tmp_path / "state" / "checkpoints.db").exists()
    assert (tmp_path / "state" / "episodic.db").exists()


def test_runtime_seed_state_refreshes_exchange(monkeypatch, tmp_path):
    _set_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
    monkeypatch.setenv("TALIM_PRICEFEED", "mock")
    monkeypatch.setenv("TALIM_INSTRUMENTS", "ES")
    monkeypatch.setenv("TALIM_STRATEGIES", "momentum-US500")

    runtime = bootstrap_runtime()
    runtime.exchange.set_fill_price("ES", 5000)
    runtime.exchange.place_order("ES", "buy", 1, strategy="manual")

    state = runtime.seed_state({"halted": True})

    assert state["halted"] is True
    assert state["active_strategies"] == ["momentum-US500"]
    assert len(state["active_positions"]) == 1
    assert state["account_balance"] == 95_000


def test_create_app_bootstraps_runtime_when_no_functions_are_injected(monkeypatch, tmp_path):
    _set_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", "secret")
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
    monkeypatch.setenv("TALIM_PRICEFEED", "mock")
    monkeypatch.setenv("TALIM_INSTRUMENTS", "ES")
    monkeypatch.setenv("TALIM_STRATEGIES", "momentum-US500")

    app = create_app()
    client = TestClient(app)

    assert app.state.talim_runtime is not None
    assert client.get("/talim/health").json() == {"status": "ok"}
