"""Tests for the live runtime bootstrap layer (WP-62)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from talim.api.bridge import create_app
from talim.app.execute_context import get_execute_context
from talim.app.nodes.risk_check import get_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.app.runtime import Runtime, RuntimeConfig, RuntimeConfigError, bootstrap_runtime
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.memory.episodic import EpisodicMemory
from talim.models.bar import OHLCVBar
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


def _bar(i: int, *, base: datetime | None = None) -> OHLCVBar:
    start = base or datetime(2026, 5, 15, 18, 0, tzinfo=timezone.utc)
    close = 7400.0 + i
    return OHLCVBar(
        instrument="US500.cash",
        timestamp=start + timedelta(minutes=5 * i),
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1000 + i,
        timeframe="5m",
    )


def _runtime_for_chart(tmp_path, price_feed=None) -> Runtime:
    return Runtime(
        config=RuntimeConfig(pricefeed_timeframe="5m", bar_window=50),
        exchange=object(),
        price_feed=price_feed or object(),
        strategies=[],
        episodic=EpisodicMemory(str(tmp_path / "episodic.db")),
        checkpointer=None,
        pnl_tracker=object(),
        backtest_history=object(),
    )


def test_operator_signal_chart_uses_scanner_history(tmp_path):
    runtime = _runtime_for_chart(tmp_path)
    bars = [_bar(i) for i in range(40)]
    for bar in bars:
        scanner_context.record_bar(bar)
    signal_bar = bars[25]
    signal_id = runtime.episodic.record_signal(
        signal={
            "instrument": "US500.cash",
            "strategy": "momentum-US500",
            "side": "short",
            "entry_price": signal_bar.close,
            "stop": signal_bar.close + 10,
            "target": signal_bar.close - 20,
            "rationale": "EMA(8) crossed below EMA(21)",
            "regime_context": "ranging",
            "timestamp": signal_bar.timestamp.isoformat(),
        }
    )

    chart = runtime.operator_signal_chart(signal_id=signal_id, before=20, after=5)

    assert chart is not None
    assert chart["status"] == "ok"
    assert chart["source"] == "scanner_history"
    assert chart["signal"]["visible_index"] == 20
    assert len(chart["candles"]) == 26
    assert chart["candles"][20]["time"] == signal_bar.timestamp.isoformat()
    assert chart["indicators"]["ema_fast"]["period"] == 8
    assert len(chart["indicators"]["ema_fast"]["values"]) == 26
    assert chart["levels"] == {
        "entry": signal_bar.close,
        "stop": signal_bar.close + 10,
        "target": signal_bar.close - 20,
    }


def test_operator_signal_chart_falls_back_to_forexcom_history(tmp_path):
    bars = [_bar(i) for i in range(60)]
    signal_bar = bars[35]

    class FakeFeed:
        def fetch_bars_before(self, instrument, *, to_timestamp_utc, count):
            assert instrument == "US500.cash"
            assert count >= 50
            return bars

    runtime = _runtime_for_chart(tmp_path, price_feed=FakeFeed())
    signal_id = runtime.episodic.record_signal(
        signal={
            "instrument": "US500.cash",
            "strategy": "momentum-US500",
            "side": "short",
            "entry_price": signal_bar.close,
            "stop": signal_bar.close + 10,
            "target": signal_bar.close - 20,
            "rationale": "EMA(8) crossed below EMA(21)",
            "regime_context": "ranging",
            "timestamp": signal_bar.timestamp.isoformat(),
        }
    )

    chart = runtime.operator_signal_chart(signal_id=signal_id, before=20, after=10)

    assert chart is not None
    assert chart["status"] == "ok"
    assert chart["source"] == "broker_history"
    assert chart["signal"]["visible_index"] == 20
    assert len(chart["candles"]) == 31


def test_operator_signal_chart_reports_unavailable_when_no_bars(tmp_path):
    runtime = _runtime_for_chart(tmp_path)
    signal_id = runtime.episodic.record_signal(
        signal={
            "instrument": "US500.cash",
            "strategy": "momentum-US500",
            "side": "short",
            "entry_price": 7427.93,
            "stop": 7437.62,
            "target": 7408.55,
            "rationale": "EMA(8) crossed below EMA(21)",
            "regime_context": "ranging",
            "timestamp": datetime(2026, 5, 15, 18, 30, tzinfo=timezone.utc).isoformat(),
        }
    )

    chart = runtime.operator_signal_chart(signal_id=signal_id, before=20, after=5)

    assert chart is not None
    assert chart["status"] == "data_unavailable"
    assert chart["candles"] == []
    assert chart["warnings"]


def test_seed_state_overlays_pending_decision_exit_levels(tmp_path):
    class FakeExchange:
        def get_positions(self):
            from talim.models.position import Position
            return [Position(
                instrument="US500.cash",
                side="short",
                qty=1.0,
                entry_price=7357.3,
                stop=0.0,
                target=0.0,
                strategy="",
                position_id="1016975723",
            )]

        def get_account_balance(self):
            return {"AUD": 50_000.0}

    class FakePnlTracker:
        def refresh(self, exchange):
            raise RuntimeError("not needed")

    runtime = Runtime(
        config=RuntimeConfig(pricefeed_timeframe="5m", strategies=("mean-reversion-US500",)),
        exchange=FakeExchange(),
        price_feed=object(),
        strategies=[],
        episodic=EpisodicMemory(str(tmp_path / "episodic.db")),
        checkpointer=None,
        pnl_tracker=FakePnlTracker(),
        backtest_history=object(),
    )
    runtime.episodic.record_decision(
        timestamp="2026-05-20T05:36:19+00:00",
        instrument="US500.cash",
        strategy="mean-reversion-US500",
        side="short",
        entry_price=7356.73,
        stop=7366.5,
        target=7349.4,
        outcome="pending",
    )

    state = runtime.seed_state()
    pos = state["active_positions"][0]

    assert pos.stop == 7366.5
    assert pos.target == 7349.4
    assert pos.strategy == "mean-reversion-US500"


def test_runtime_config_parses_regime_filters(monkeypatch, tmp_path):
    _set_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "TALIM_REGIME_FILTERS",
        "momentum-US500:atr-high,rsi2-reversion:atr-low",
    )

    config = RuntimeConfig.from_env()

    assert dict(config.regime_filters) == {
        "momentum-US500": "atr-high",
        "rsi2-reversion": "atr-low",
    }

    monkeypatch.delenv("TALIM_REGIME_FILTERS")
    assert RuntimeConfig.from_env().regime_filters == ()
