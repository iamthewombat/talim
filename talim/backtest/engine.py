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

from talim.backtest.costs import ZERO_COSTS, BacktestCostConfig
from talim.backtest.data_loader import load_dataframe, load_ohlcv
from talim.backtest.metrics import Trade, compute_metrics
from talim.backtest.sizing import BacktestSizingConfig, size_trade
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


def _simulate(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    instrument: str,
    sizing: BacktestSizingConfig | None = None,
    costs: BacktestCostConfig | None = None,
) -> list[Trade]:
    """Replay bars through a strategy and collect simulated trades."""
    strategy.reset()
    sizing = sizing or BacktestSizingConfig()
    costs = costs or ZERO_COSTS
    available_capital = sizing.initial_capital
    trades: list[Trade] = []

    bars = [_row_to_bar(row, instrument) for row in df.itertuples(index=False)]
    i = 0
    n = len(bars)
    while i < n:
        sig = strategy.on_bar(bars[i])
        if sig is None:
            i += 1
            continue

        qty = size_trade(
            entry_price=sig.entry_price,
            stop_price=sig.stop,
            available_capital=available_capital,
            config=sizing,
        )
        if qty <= 0:
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
        trade = Trade(
            side=sig.side,
            entry_price=costs.entry_fill(sig.entry_price, sig.side),
            exit_price=costs.exit_fill(exit_price, sig.side),
            qty=qty,
            fees=costs.round_trip_commission(qty),
        )
        trades.append(trade)
        if sizing.compound:
            available_capital += trade.pnl

    return trades


def run_backtest(
    strategy_name: str,
    param_variants: list[dict] | None = None,
    matched_dates: list[date] | None = None,
    data_dir: str | Path = "data",
    instrument: str = "ES",
    timeframe: str | None = None,
    df: pd.DataFrame | None = None,
    sizing: BacktestSizingConfig | None = None,
    costs: BacktestCostConfig | None = None,
) -> list[BacktestResult]:
    """Run a backtest for `strategy_name` across one or more parameter variants.

    Args:
        strategy_name: Name of the strategy to load via `load_strategy`.
        param_variants: List of parameter dicts. Empty/None → single default run.
        matched_dates: Restrict to these session dates (parquet layouts only).
        data_dir: Directory containing parquet OHLCV files.
        instrument: Instrument symbol (used for the bar's `instrument` field).
        df: In-memory DataFrame to use instead of loading from disk (for tests).
        sizing: Position sizing model. Defaults to fixed 1-unit trades.
        costs: Spread/slippage/commission model. Defaults to frictionless
            (WP-86; load standardised venue assumptions via
            `talim.backtest.costs.load_cost_config`).

    Returns:
        list[BacktestResult] sorted by sharpe_ratio descending.
    """
    variants = param_variants or [{}]

    # WP-72: validate every variant up front — before we touch disk — so a
    # bad variant fails the run without loading data or burning CPU. Reuse
    # one probe instance of the strategy; not used for simulation.
    probe = load_strategy(strategy_name)
    for variant in variants:
        if variant:
            probe.load_params(variant)

    if df is not None:
        data = load_dataframe(df)
    else:
        data = load_ohlcv(
            data_dir,
            instrument,
            matched_dates=matched_dates,
            timeframe=timeframe,
        )

    results: list[BacktestResult] = []
    for variant in variants:
        strategy = load_strategy(strategy_name)
        if variant:
            strategy.load_params(variant)
        trades = _simulate(strategy, data, instrument, sizing=sizing, costs=costs)
        m = compute_metrics(trades)
        period_start = str(data["timestamp"].iloc[0]) if "timestamp" in data and len(data) else ""
        period_end = str(data["timestamp"].iloc[-1]) if "timestamp" in data and len(data) else ""
        basis = float(data["close"].iloc[0]) if "close" in data and len(data) else 0.0
        capital_basis = (sizing.initial_capital if sizing is not None else 0.0) or basis
        return_pct = float(m["net_pnl"] / capital_basis) if capital_basis else 0.0
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
                return_pct=return_pct,
                sortino_ratio=m.get("sortino_ratio", 0.0),
                profit_factor=m.get("profit_factor", 0.0),
                period_start=period_start,
                period_end=period_end,
            )
        )

    results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
    return results
