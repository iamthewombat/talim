"""Backtest engine (WP-12).

Runs strategies bar-by-bar against historical OHLCV data using the same
`on_bar` interface as live trading. For each emitted Signal, simulates a
single round-trip trade where the exit is whichever of stop/target is touched
first by subsequent bars (intrabar; conservative — stop is checked before
target on the same bar). If neither is touched the trade exits at the last
close of the data window.

Returns a list of `BacktestResult`, one per param variant, sorted by Sharpe.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from talim.backtest.data_loader import load_dataframe, load_ohlcv
from talim.backtest.metrics import Trade, compute_metrics
from talim.models.backtest import BacktestResult
from talim.models.bar import OHLCVBar
from talim.strategy.base import BaseStrategy
from talim.strategy.loader import load_strategy


def _row_to_bar(row, instrument: str) -> OHLCVBar:
    return OHLCVBar(
        instrument=instrument,
        timestamp=row.timestamp.to_pydatetime() if hasattr(row.timestamp, "to_pydatetime") else row.timestamp,
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        volume=float(row.volume),
    )


def _simulate(strategy: BaseStrategy, df: pd.DataFrame, instrument: str) -> list[Trade]:
    """Replay bars through a strategy and collect simulated trades."""
    strategy.reset()
    trades: list[Trade] = []

    bars = [_row_to_bar(row, instrument) for row in df.itertuples(index=False)]
    i = 0
    n = len(bars)
    while i < n:
        sig = strategy.on_bar(bars[i])
        if sig is None:
            i += 1
            continue

        # Find the exit: scan forward until stop or target hit.
        exit_price: float | None = None
        for j in range(i + 1, n):
            b = bars[j]
            if sig.side == "long":
                if b.low <= sig.stop:
                    exit_price = sig.stop
                    break
                if b.high >= sig.target:
                    exit_price = sig.target
                    break
            else:  # short
                if b.high >= sig.stop:
                    exit_price = sig.stop
                    break
                if b.low <= sig.target:
                    exit_price = sig.target
                    break
        if exit_price is None:
            exit_price = bars[-1].close
            i = n  # consume the rest
        else:
            i = j + 1
        trades.append(Trade(side=sig.side, entry_price=sig.entry_price, exit_price=exit_price))

    return trades


def run_backtest(
    strategy_name: str,
    param_variants: list[dict] | None = None,
    matched_dates: list[date] | None = None,
    data_dir: str | Path = "data",
    instrument: str = "ES",
    timeframe: str | None = None,
    df: pd.DataFrame | None = None,
) -> list[BacktestResult]:
    """Run a backtest for `strategy_name` across one or more parameter variants.

    Args:
        strategy_name: Name of the strategy to load via `load_strategy`.
        param_variants: List of parameter dicts. Empty/None → single default run.
        matched_dates: Restrict to these session dates (parquet layouts only).
        data_dir: Directory containing parquet OHLCV files.
        instrument: Instrument symbol (used for the bar's `instrument` field).
        df: In-memory DataFrame to use instead of loading from disk (for tests).

    Returns:
        list[BacktestResult] sorted by sharpe_ratio descending.
    """
    if df is not None:
        data = load_dataframe(df)
    else:
        data = load_ohlcv(
            data_dir,
            instrument,
            matched_dates=matched_dates,
            timeframe=timeframe,
        )

    variants = param_variants or [{}]
    results: list[BacktestResult] = []
    for variant in variants:
        strategy = load_strategy(strategy_name)
        if variant:
            strategy.load_params(variant)
        trades = _simulate(strategy, data, instrument)
        m = compute_metrics(trades)
        results.append(
            BacktestResult(
                strategy_name=strategy_name,
                net_pnl=m["net_pnl"],
                sharpe_ratio=m["sharpe_ratio"],
                max_drawdown=m["max_drawdown"],
                win_rate=m["win_rate"],
                total_trades=m["total_trades"],
                param_variant=dict(variant),
                matched_dates=list(matched_dates or []),
            )
        )

    results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
    return results
