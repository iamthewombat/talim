"""Tests for the MCP tool wrappers (WP-27)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from talim.app.tools import (
    ToolContext,
    TOOLS,
    get_pnl,
    get_positions,
    propose_strategy_update,
    query_episodic_memory,
    run_backtest,
)
from talim.app.tools.server import list_tool_names
from talim.app.tools.wrappers import ToolError
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.llm.mock import MockLLMClient
from talim.memory.episodic import EpisodicMemory


def _bars(n: int = 120) -> pd.DataFrame:
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.15)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-06-15 09:30", periods=n, freq="5min"),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10_000.0),
    })


def test_registry_lists_expected_tools():
    names = list_tool_names()
    assert set(names) == {
        "get_positions",
        "get_pnl",
        "run_backtest",
        "propose_strategy_update",
        "query_episodic_memory",
    }
    # TOOLS entries are (name, callable, description) triples.
    for name, fn, desc in TOOLS:
        assert callable(fn)
        assert isinstance(desc, str) and desc


def test_get_positions_and_pnl_round_trip():
    ex = MockExchange(starting_balance=50_000.0)
    ex.set_fill_price("ES", 5400.0)
    ex.place_order(instrument="ES", side="buy", qty=1.0, strategy="momentum-ES")
    ctx = ToolContext(exchange=ex)

    out = get_positions(ctx)
    assert any(p["instrument"] == "ES" for p in out["positions"])

    pnl = get_pnl(ctx)
    assert pnl["position_count"] >= 1
    assert "balance" in pnl


def test_run_backtest_returns_results():
    ctx = ToolContext()
    out = run_backtest(
        ctx,
        strategy_name="momentum-ES",
        param_variants=[{"ema_fast_period": 8}, {"ema_fast_period": 5}],
        df=_bars(),
    )
    assert len(out["results"]) == 2
    for r in out["results"]:
        assert r["strategy_name"] == "momentum-ES"
        assert "sharpe_ratio" in r


def test_propose_strategy_update_parses_json():
    llm = MockLLMClient(
        responder=lambda method, prompt: '{"ema_fast_period": 5, "rationale": "tighten"}'
    )
    out = propose_strategy_update(
        ToolContext(llm=llm),
        strategy_name="momentum-ES",
        current_params={"ema_fast_period": 8},
        regime="momentum",
    )
    assert out["proposal"] == {"ema_fast_period": 5, "rationale": "tighten"}


def test_query_episodic_memory(tmp_path):
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    mem.record_decision(
        timestamp="2025-06-15T09:30:00",
        instrument="ES",
        strategy="momentum-ES",
        side="long",
        entry_price=5000.0,
        stop=4980.0,
        target=5040.0,
    )
    out = query_episodic_memory(ToolContext(episodic=mem), instrument="ES")
    assert out["total"] == 1
    assert out["decisions"][0]["strategy"] == "momentum-ES"
    mem.close()


def test_missing_dependency_raises():
    with pytest.raises(ToolError):
        get_positions(ToolContext())  # no exchange wired
