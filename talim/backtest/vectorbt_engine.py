"""Vectorbt-backed backtest engine (WP-29 — optional alternate path).

The default Talim backtester (`talim/backtest/engine.py`) replays bars
through each strategy's own `on_bar` method so live trading and backtests
share code by construction. That's the right default — but for parameter
sweeps it's slow.

This module provides a faster vectorised path using `vectorbt`. It only
supports the two PoC strategies (`momentum-ES`, `mean-reversion-ES`) since
each strategy needs a hand-written translation from `on_bar` logic to
vectorbt entry/exit boolean series. A parity test (skipped if vectorbt
isn't installed) checks the new path stays within tolerance of the on_bar
engine on a known dataset.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pandas as pd

from talim.backtest.metrics import Trade, compute_metrics
from talim.models.backtest import BacktestResult


def vectorbt_available() -> bool:
    return importlib.util.find_spec("vectorbt") is not None


# ---------------------------------------------------------------------------
# Strategy → entry/exit signal translators
# ---------------------------------------------------------------------------

def _momentum_signals(df: pd.DataFrame, params: dict) -> tuple[pd.Series, pd.Series]:
    fast = int(params.get("ema_fast_period", 8))
    slow = int(params.get("ema_slow_period", 21))
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
    cross_dn = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
    return cross_up.fillna(False), cross_dn.fillna(False)


def _mean_reversion_signals(
    df: pd.DataFrame, params: dict
) -> tuple[pd.Series, pd.Series]:
    period = int(params.get("bb_period", 20))
    sigma = float(params.get("bb_std", 2.0))
    close = df["close"]
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = mid + sigma * sd
    lower = mid - sigma * sd
    long_entry = close < lower
    long_exit = close > mid
    return long_entry.fillna(False), long_exit.fillna(False)


_TRANSLATORS = {
    "momentum-ES": _momentum_signals,
    "momentum-AU200": _momentum_signals,
    "mean-reversion-ES": _mean_reversion_signals,
}


def supported_strategies() -> list[str]:
    return list(_TRANSLATORS)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class VectorbtUnsupported(RuntimeError):
    pass


def _run_one(
    strategy_name: str, params: dict, df: pd.DataFrame
) -> BacktestResult:
    if not vectorbt_available():
        raise VectorbtUnsupported(
            "vectorbt is not installed. pip install vectorbt"
        )
    if strategy_name not in _TRANSLATORS:
        raise VectorbtUnsupported(
            f"vectorbt path has no translator for {strategy_name}; "
            f"supported: {supported_strategies()}"
        )

    import vectorbt as vbt  # type: ignore

    entries, exits = _TRANSLATORS[strategy_name](df, params)
    pf = vbt.Portfolio.from_signals(
        df["close"], entries, exits, init_cash=100_000.0, freq="5min"
    )
    trades_records = pf.trades.records_readable
    trades: list[Trade] = []
    for _, row in trades_records.iterrows():
        side = "long"  # vbt's from_signals here is long-only
        trades.append(
            Trade(
                side=side,
                entry_price=float(row["Avg Entry Price"]),
                exit_price=float(row["Avg Exit Price"]),
            )
        )
    m = compute_metrics(trades)
    return BacktestResult(
        strategy_name=strategy_name,
        net_pnl=m["net_pnl"],
        sharpe_ratio=m["sharpe_ratio"],
        max_drawdown=m["max_drawdown"],
        win_rate=m["win_rate"],
        total_trades=m["total_trades"],
        param_variant=dict(params),
    )


def run_vectorbt_backtest(
    strategy_name: str,
    param_variants: list[dict] | None = None,
    df: pd.DataFrame | None = None,
) -> list[BacktestResult]:
    if df is None:
        raise ValueError("run_vectorbt_backtest requires an in-memory DataFrame")
    variants = param_variants or [{}]
    results = [_run_one(strategy_name, v, df) for v in variants]
    results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
    return results
