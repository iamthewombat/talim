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

from datetime import date, time
from pathlib import Path
from typing import Iterable

import pandas as pd

from talim.backtest.costs import ZERO_COSTS, BacktestCostConfig
from talim.backtest.data_loader import load_dataframe, load_ohlcv
from talim.backtest.metrics import Trade, compute_equity_metrics, compute_metrics
from talim.backtest.sizing import BacktestSizingConfig, size_trade
from talim.models.backtest import BacktestResult
from talim.models.bar import OHLCVBar
from talim.regime.atr_gate import atr_regime_mask
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


def _align_spread(data: pd.DataFrame, quotes: pd.DataFrame) -> "pd.Series":
    """Per-bar spread aligned to `data` rows (backward asof, gaps filled with median)."""
    merged = pd.merge_asof(
        data[["timestamp"]],
        quotes,
        on="timestamp",
        direction="backward",
        tolerance=pd.Timedelta("2D"),
    )
    spread = (merged["ask_close"] - merged["bid_close"]).clip(lower=0.0)
    fallback = spread.median()
    if pd.isna(fallback):
        raise ValueError("quotes frame produced no usable spreads to align")
    return spread.fillna(fallback).reset_index(drop=True)


def _in_session(ts, window: tuple[time, time]) -> bool:
    t = ts.time() if hasattr(ts, "time") else ts
    start, end = window
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # window wraps midnight


def _simulate(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    instrument: str,
    sizing: BacktestSizingConfig | None = None,
    costs: BacktestCostConfig | None = None,
    session_window: tuple[time, time] | None = None,
    spread_arr: "pd.Series | None" = None,
    slippage_frac: float = 0.25,
    entry_mask: "pd.Series | None" = None,
) -> tuple[list[Trade], list[tuple]]:
    """Replay bars through a strategy; return (trades, equity_curve).

    `equity_curve` is [(timestamp, cumulative_pnl), ...] marked to market at
    every bar close (realised + open-position unrealised).

    `session_window` (UTC times) suppresses NEW entries outside the window;
    indicators still update on every bar and open trades exit normally.

    When `spread_arr` is given (per-bar spread aligned to `df` rows), fills
    are charged that bar's half-spread plus `slippage_frac` x spread per
    side instead of the flat `costs` spread/slippage. Commission still comes
    from `costs`.
    """
    strategy.reset()
    sizing = sizing or BacktestSizingConfig()
    costs = costs or ZERO_COSTS
    available_capital = sizing.initial_capital
    trades: list[Trade] = []
    equity_curve: list[tuple] = []
    realized = 0.0

    bars = [_row_to_bar(row, instrument) for row in df.itertuples(index=False)]
    n = len(bars)

    def _fill(price: float, side: str, idx: int, is_entry: bool) -> float:
        if spread_arr is not None:
            adj = float(spread_arr.iloc[idx]) * (0.5 + slippage_frac)
            adverse_up = (side == "long") == is_entry
            return price + adj if adverse_up else price - adj
        if is_entry:
            return costs.entry_fill(price, side)
        return costs.exit_fill(price, side)

    open_sig = None
    open_qty = 0.0
    open_entry_fill = 0.0

    def _close(exit_price: float, exit_idx: int) -> None:
        nonlocal open_sig, open_qty, available_capital, realized
        trade = Trade(
            side=open_sig.side,
            entry_price=open_entry_fill,
            exit_price=_fill(exit_price, open_sig.side, exit_idx, is_entry=False),
            qty=open_qty,
            fees=costs.round_trip_commission(open_qty),
        )
        trades.append(trade)
        realized += trade.pnl
        if sizing.compound:
            available_capital += trade.pnl
        open_sig = None
        open_qty = 0.0

    def _process_bar(idx: int, bar: OHLCVBar) -> None:
        nonlocal open_sig, open_qty, open_entry_fill
        # Strategy sees every bar so indicator state has no gaps while a
        # position is open; its signals are ignored until we are flat again.
        sig = strategy.on_bar(bar)

        if open_sig is not None:
            # Bracket exits first (intrabar; conservative — stop before target),
            # then the strategy's own condition exit at the bar close.
            # A stop/target <= 0 means "no bracket on that side" — same
            # semantics as the live position monitor.
            if open_sig.side == "long":
                if open_sig.stop > 0 and bar.low <= open_sig.stop:
                    _close(open_sig.stop, idx)
                    return
                if open_sig.target > 0 and bar.high >= open_sig.target:
                    _close(open_sig.target, idx)
                    return
            else:
                if open_sig.stop > 0 and bar.high >= open_sig.stop:
                    _close(open_sig.stop, idx)
                    return
                if open_sig.target > 0 and bar.low <= open_sig.target:
                    _close(open_sig.target, idx)
                    return
            if strategy.exit_signal(bar, open_sig.side):
                _close(bar.close, idx)
            return

        if sig is None:
            return
        if session_window is not None and not _in_session(bar.timestamp, session_window):
            return
        if entry_mask is not None and not bool(entry_mask.iloc[idx]):
            return
        qty = size_trade(
            entry_price=sig.entry_price,
            stop_price=sig.stop,
            available_capital=available_capital,
            config=sizing,
        )
        if qty <= 0:
            return
        open_sig = sig
        open_qty = qty
        open_entry_fill = _fill(sig.entry_price, sig.side, idx, is_entry=True)

    for idx, bar in enumerate(bars):
        _process_bar(idx, bar)
        if open_sig is not None:
            direction = 1.0 if open_sig.side == "long" else -1.0
            unrealized = (bar.close - open_entry_fill) * direction * open_qty
        else:
            unrealized = 0.0
        equity_curve.append((bar.timestamp, realized + unrealized))

    if open_sig is not None:
        _close(bars[-1].close, n - 1)
        equity_curve[-1] = (bars[-1].timestamp, realized)

    return trades, equity_curve


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
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    session_window: tuple[time, time] | None = None,
    quotes: pd.DataFrame | None = None,
    slippage_frac: float = 0.25,
    regime_filter: str | None = None,
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
        start: Drop bars before this timestamp (use to exclude OOS holdout).
        end: Drop bars at/after this timestamp (exclusive).
        session_window: (start, end) UTC times; new entries only inside the
            window. Indicators still see all bars.
        quotes: Per-bar bid/ask closes (timestamp, bid_close, ask_close) from
            `load_quotes`. When given, fills use each bar's actual spread
            (half-spread + slippage_frac x spread per side) instead of the
            flat costs spread/slippage.
        slippage_frac: Slippage per side as a fraction of the bar's spread
            (per-bar cost mode only).
        regime_filter: 'atr-high' or 'atr-low' — allow NEW entries only when
            ATR(14) is above/below its 100-bar average. Indicators and open
            trades are unaffected.

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

    if start is not None:
        data = data[data["timestamp"] >= start]
    if end is not None:
        data = data[data["timestamp"] < end]
    if (start is not None or end is not None):
        data = data.reset_index(drop=True)
        if data.empty:
            raise ValueError(
                f"No bars left after applying window start={start} end={end}; "
                "check the requested dates against available data."
            )

    spread_arr = _align_spread(data, quotes) if quotes is not None else None
    entry_mask = atr_regime_mask(data, regime_filter) if regime_filter else None

    results: list[BacktestResult] = []
    for variant in variants:
        strategy = load_strategy(strategy_name)
        if variant:
            strategy.load_params(variant)
        trades, equity_curve = _simulate(
            strategy,
            data,
            instrument,
            sizing=sizing,
            costs=costs,
            session_window=session_window,
            spread_arr=spread_arr,
            slippage_frac=slippage_frac,
            entry_mask=entry_mask,
        )
        m = compute_metrics(trades)
        period_start = str(data["timestamp"].iloc[0]) if "timestamp" in data and len(data) else ""
        period_end = str(data["timestamp"].iloc[-1]) if "timestamp" in data and len(data) else ""
        basis = float(data["close"].iloc[0]) if "close" in data and len(data) else 0.0
        capital_basis = (sizing.initial_capital if sizing is not None else 0.0) or basis
        return_pct = float(m["net_pnl"] / capital_basis) if capital_basis else 0.0
        em = compute_equity_metrics(equity_curve, capital_basis)
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
                annualised_sharpe=em["annualised_sharpe"],
                annualised_sortino=em["annualised_sortino"],
                max_drawdown_pct=em["max_drawdown_pct"],
                yearly_pnl=em["yearly_pnl"],
                profitable_years_frac=em["profitable_years_frac"],
                max_year_contribution=em["max_year_contribution"],
            )
        )

    results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
    return results
