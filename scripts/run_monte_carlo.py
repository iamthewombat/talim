#!/usr/bin/env python3
"""Monte Carlo robustness analysis of a strategy or portfolio backtest.

Simulates the leg(s) exactly like run_portfolio_backtest.py, then applies a
stationary block bootstrap to the combined daily equity changes to produce
distributions of net P&L, annualised Sharpe and max drawdown. Use the 5th
percentile of max drawdown (bad tail) for sizing decisions and the Sharpe
p5/prob-below-0 as a significance check on small samples.

Example (live 3-leg book, in-sample):
  run_monte_carlo.py --instrument US500.proxy --timeframe 1d \
    --data-dir data/dukascopy --costs-venue dukascopy-proxy \
    --end 2025-01-01 --per-bar-costs \
    --leg '{"strategy": "momentum-US500", "regime_filter": "atr-high"}' \
    --leg '{"strategy": "rsi2-reversion", "regime_filter": "atr-low"}' \
    --leg '{"strategy": "ibs-reversion"}'
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from talim.backtest.costs import DEFAULT_COSTS_PATH, ZERO_COSTS, load_cost_config
from talim.backtest.data_loader import load_ohlcv, load_quotes
from talim.backtest.engine import _align_spread, _simulate
from talim.backtest.monte_carlo import monte_carlo_summary
from talim.backtest.sizing import BacktestSizingConfig
from talim.regime.atr_gate import atr_regime_mask
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
        help="Allow NEW entries only from this UTC timestamp (OOS walk-forward)",
    )
    parser.add_argument("--per-bar-costs", action="store_true")
    parser.add_argument("--slippage-frac", type=float, default=0.25)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--fixed-qty", type=float, default=1.0)
    parser.add_argument("--sims", type=int, default=2000)
    parser.add_argument("--block-days", type=float, default=20.0,
                        help="Mean bootstrap block length in days")
    parser.add_argument("--seed", type=int, default=7)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    legs = [json.loads(item) for item in args.leg]
    if not legs:
        print("error: need at least one --leg spec", file=sys.stderr)
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
    if args.per_bar_costs:
        quotes = load_quotes(args.data_dir, args.instrument, args.timeframe)
        spread_arr = _align_spread(data, quotes)

    entries_ts = pd.Timestamp(args.entries_start, tz="UTC") if args.entries_start else None
    time_mask = (
        (data["timestamp"] >= entries_ts).reset_index(drop=True)
        if entries_ts is not None
        else None
    )

    sizing = BacktestSizingConfig(
        initial_capital=args.initial_capital, fixed_qty=args.fixed_qty
    )

    combined_equity = None
    total_trades = 0
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
        total_trades += len(trades)
        if combined_equity is None:
            combined_equity = [pnl for _, pnl in curve]
            timestamps = [ts for ts, _ in curve]
        else:
            combined_equity = [a + b for a, b in zip(combined_equity, [p for _, p in curve])]

    curve = list(zip(timestamps, combined_equity))
    if entries_ts is not None:
        curve = [(ts, pnl) for ts, pnl in curve if ts >= entries_ts]

    summary = monte_carlo_summary(
        curve,
        args.initial_capital,
        n_sims=args.sims,
        mean_block_days=args.block_days,
        seed=args.seed,
    )

    payload = {
        "instrument": args.instrument,
        "timeframe": args.timeframe,
        "legs": legs,
        "window": {
            "start": args.start,
            "end": args.end,
            "entries_start": args.entries_start,
        },
        "costs": {
            "mode": "per-bar" if args.per_bar_costs else "flat",
            "venue": args.costs_venue,
            "slippage_frac": args.slippage_frac,
        },
        "total_trades": total_trades,
        "monte_carlo": summary,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
