#!/usr/bin/env python3
"""Run multiple strategy legs on the same data and score the combined book.

Each leg is simulated independently (own strategy, params, regime filter) on
the same bar series and capital base; combined equity is the element-wise sum
of the per-leg mark-to-market curves, so the portfolio metrics reflect real
daily offsets between legs rather than concatenated trade lists alone.

Example:
  run_portfolio_backtest.py --instrument US500.proxy --timeframe 1d \
    --data-dir data/dukascopy --costs-venue dukascopy-proxy \
    --end 2025-01-01 --per-bar-costs \
    --leg '{"strategy": "momentum-US500", "regime_filter": "atr-high"}' \
    --leg '{"strategy": "rsi2-reversion", "regime_filter": "atr-low"}'
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from talim.backtest.costs import DEFAULT_COSTS_PATH, ZERO_COSTS, load_cost_config
from talim.backtest.data_loader import load_ohlcv, load_quotes
from talim.backtest.engine import _align_spread, _simulate
from talim.regime.atr_gate import atr_regime_mask
from talim.backtest.metrics import compute_equity_metrics, compute_metrics
from talim.backtest.sizing import BacktestSizingConfig
from talim.strategy.loader import load_strategy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--leg",
        action="append",
        required=True,
        help=(
            'JSON leg spec, repeatable: {"strategy": "name", '
            '"regime_filter": "atr-high"|"atr-low"|null, "params": {...}}'
        ),
    )
    parser.add_argument("--costs-venue", default=None)
    parser.add_argument("--costs-config", default=str(DEFAULT_COSTS_PATH))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--entries-start",
        default=None,
        help=(
            "Allow NEW entries only from this UTC timestamp; earlier bars still "
            "warm indicators/regime stats. Metrics are computed from this point. "
            "Use for OOS walk-forward so warmup does not eat the holdout."
        ),
    )
    parser.add_argument("--per-bar-costs", action="store_true")
    parser.add_argument("--slippage-frac", type=float, default=0.25)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--fixed-qty", type=float, default=1.0)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    legs = [json.loads(item) for item in args.leg]
    if len(legs) < 2:
        print("error: need at least two --leg specs for a portfolio", file=sys.stderr)
        return 2

    costs = None
    if args.costs_venue:
        costs = load_cost_config(args.costs_venue, args.instrument, path=args.costs_config)
    else:
        print("warning: running frictionless.", file=sys.stderr)

    data = load_ohlcv(args.data_dir, args.instrument, timeframe=args.timeframe)
    if args.start:
        data = data[data["timestamp"] >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        data = data[data["timestamp"] < pd.Timestamp(args.end, tz="UTC")]
    data = data.reset_index(drop=True)
    if data.empty:
        print("error: no bars left after window", file=sys.stderr)
        return 2

    spread_arr = None
    quotes = None
    if args.per_bar_costs:
        quotes = load_quotes(args.data_dir, args.instrument, args.timeframe)
        spread_arr = _align_spread(data, quotes)

    entries_ts = pd.Timestamp(args.entries_start, tz="UTC") if args.entries_start else None
    time_mask = (
        (data["timestamp"] >= entries_ts).reset_index(drop=True)
        if entries_ts is not None
        else None
    )

    def _trim_curve(curve):
        if entries_ts is None:
            return curve
        return [(ts, pnl) for ts, pnl in curve if ts >= entries_ts]

    sizing = BacktestSizingConfig(
        initial_capital=args.initial_capital, fixed_qty=args.fixed_qty
    )

    all_trades = []
    combined_equity = None
    leg_reports = []
    for spec in legs:
        strategy = load_strategy(spec["strategy"])
        if spec.get("params"):
            strategy.load_params(spec["params"])
        regime = spec.get("regime_filter")
        entry_mask = atr_regime_mask(data, regime) if regime else None
        if time_mask is not None:
            entry_mask = time_mask if entry_mask is None else (entry_mask & time_mask)
        trades, curve = _simulate(
            strategy,
            data,
            args.instrument,
            sizing=sizing,
            costs=costs or ZERO_COSTS,
            spread_arr=spread_arr,
            slippage_frac=args.slippage_frac,
            entry_mask=entry_mask,
        )
        all_trades.extend(trades)
        equity_vals = [pnl for _, pnl in curve]
        if combined_equity is None:
            combined_equity = equity_vals
            timestamps = [ts for ts, _ in curve]
        else:
            combined_equity = [a + b for a, b in zip(combined_equity, equity_vals)]
        m = compute_metrics(trades)
        em = compute_equity_metrics(_trim_curve(curve), args.initial_capital)
        leg_reports.append(
            {
                "strategy": spec["strategy"],
                "regime_filter": regime,
                "params": spec.get("params") or {},
                "net_pnl": m["net_pnl"],
                "total_trades": m["total_trades"],
                "win_rate": m["win_rate"],
                "profit_factor": m["profit_factor"],
                "annualised_sharpe": em["annualised_sharpe"],
                "max_drawdown_pct": em["max_drawdown_pct"],
                "yearly_pnl": em["yearly_pnl"],
                "profitable_years_frac": em["profitable_years_frac"],
                "max_year_contribution": em["max_year_contribution"],
            }
        )

    combined_curve = _trim_curve(list(zip(timestamps, combined_equity)))
    cm = compute_metrics(all_trades)
    cem = compute_equity_metrics(combined_curve, args.initial_capital)

    payload = {
        "instrument": args.instrument,
        "timeframe": args.timeframe,
        "window": {"start": args.start, "end": args.end, "entries_start": args.entries_start},
        "costs": {
            "mode": "per-bar" if args.per_bar_costs else "flat",
            "venue": args.costs_venue,
            "slippage_frac": args.slippage_frac,
        },
        "legs": leg_reports,
        "combined": {
            "net_pnl": cm["net_pnl"],
            "total_trades": cm["total_trades"],
            "win_rate": cm["win_rate"],
            "profit_factor": cm["profit_factor"],
            "annualised_sharpe": cem["annualised_sharpe"],
            "annualised_sortino": cem["annualised_sortino"],
            "max_drawdown_pct": cem["max_drawdown_pct"],
            "yearly_pnl": cem["yearly_pnl"],
            "profitable_years_frac": cem["profitable_years_frac"],
            "max_year_contribution": cem["max_year_contribution"],
        },
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
