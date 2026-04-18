"""Tests for the optional vectorbt backtest path (WP-29)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from talim.backtest.engine import run_backtest
from talim.backtest.vectorbt_engine import (
    VectorbtUnsupported,
    run_vectorbt_backtest,
    supported_strategies,
    vectorbt_available,
)
from talim.models.backtest import BacktestRequest


def _bars(n: int = 200) -> pd.DataFrame:
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.15)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-06-15 09:30", periods=n, freq="5min"),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10_000.0),
    })


def test_supported_strategies_lists_both_poc_strats():
    assert "momentum-ES" in supported_strategies()
    assert "momentum-AU200" in supported_strategies()
    assert "mean-reversion-ES" in supported_strategies()


def test_request_engine_field_default():
    req = BacktestRequest(strategy_name="momentum-ES")
    assert req.engine == "on_bar"


def test_unsupported_strategy_raises():
    if not vectorbt_available():
        with pytest.raises(VectorbtUnsupported):
            run_vectorbt_backtest("nonexistent-strategy", [{}], df=_bars())
    else:
        with pytest.raises(VectorbtUnsupported):
            run_vectorbt_backtest("nonexistent-strategy", [{}], df=_bars())


def test_unavailable_falls_back_to_on_bar_in_node():
    """When vectorbt isn't installed, the node should fall back cleanly."""
    from talim.app.nodes.backtest_run import backtest_run

    req = BacktestRequest(
        strategy_name="momentum-ES",
        param_variants=[{"ema_fast_period": 8}],
        engine="vectorbt",
    )
    state = backtest_run({"pending_backtest": req})
    # Either path must populate backtest_result without raising.
    assert "backtest_result" in state
    if state["backtest_result"] is not None:
        assert state["backtest_result"][0].strategy_name == "momentum-ES"


@pytest.mark.skipif(not vectorbt_available(), reason="vectorbt not installed")
def test_vectorbt_runs_and_produces_metrics():
    """Sanity check: vectorbt path produces a well-formed BacktestResult.

    True numeric parity with the on_bar engine isn't expected — the on_bar
    engine exits at stop/target prices, while the vectorbt path here is a
    crossover-only entry/exit translation with no stop/target concept.
    """
    df = _bars(300)
    vb = run_vectorbt_backtest("momentum-ES", param_variants=[{}], df=df)
    assert len(vb) == 1
    assert vb[0].strategy_name == "momentum-ES"
    assert vb[0].total_trades >= 0
    # Both engines should be runnable on the same df without raising.
    ob = run_backtest("momentum-ES", param_variants=[{}], df=df)
    assert ob[0].strategy_name == "momentum-ES"
