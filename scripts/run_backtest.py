#!/usr/bin/env python3
"""Run a Talim backtest from the command line and print JSON results."""

from __future__ import annotations

import argparse
import json
import sys

from talim.backtest.costs import DEFAULT_COSTS_PATH, load_cost_config
from talim.backtest.engine import run_backtest
from talim.backtest.history import BacktestHistory, default_history_path
from talim.backtest.sizing import BacktestSizingConfig
from talim.models.backtest import BacktestRequest
from talim.strategy.params import StrategyParamError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, help="Strategy name, e.g. momentum-US500")
    parser.add_argument(
        "--instrument",
        required=True,
        help="Canonical instrument id, e.g. US500.cash",
    )
    parser.add_argument(
        "--timeframe",
        help="Timeframe parquet to load (e.g. 5m, 1h). Required when using venue data roots like data/forexcom/ or data/ig/",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory. For venue-specific ingested data pass data/forexcom or data/ig.",
    )
    parser.add_argument(
        "--params",
        action="append",
        default=[],
        help='JSON param variant. Repeat to run multiple variants, e.g. --params \'{"ema_fast_period":10}\'',
    )
    parser.add_argument(
        "--history-db",
        default=None,
        help="Path to backtest history SQLite DB (default: $TALIM_BACKTEST_HISTORY_DB or state/backtest_history.db)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip recording this run to the backtest history store",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional free-text notes attached to each history row",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100_000.0,
        help="Starting capital for return and position sizing calculations",
    )
    parser.add_argument(
        "--sizing-mode",
        choices=("fixed_qty", "risk_pct"),
        default="fixed_qty",
        help="Position sizing model to use for simulated trades",
    )
    parser.add_argument(
        "--fixed-qty",
        type=float,
        default=1.0,
        help="Quantity per trade when --sizing-mode=fixed_qty",
    )
    parser.add_argument(
        "--risk-per-trade-pct",
        type=float,
        default=0.01,
        help="Fraction of available capital to risk per trade when --sizing-mode=risk_pct",
    )
    parser.add_argument(
        "--max-position-qty",
        type=float,
        default=None,
        help="Optional cap on quantity per simulated trade",
    )
    parser.add_argument(
        "--max-total-exposure",
        type=float,
        default=None,
        help="Optional cap on notional exposure per simulated trade",
    )
    parser.add_argument(
        "--no-compound",
        action="store_true",
        help="Disable compounding for risk_pct sizing",
    )
    parser.add_argument(
        "--costs-venue",
        default=None,
        help=(
            "Apply standardised spread/slippage/commission assumptions for this "
            "venue (e.g. forexcom, ig, dukascopy-proxy) from config/backtest_costs.json. "
            "Omit to run frictionless (a warning is printed)."
        ),
    )
    parser.add_argument(
        "--costs-config",
        default=str(DEFAULT_COSTS_PATH),
        help="Path to the cost assumptions JSON (default: config/backtest_costs.json)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        variants = [json.loads(item) for item in args.params] or [{}]
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in --params: {exc}", file=sys.stderr)
        return 2

    costs = None
    if args.costs_venue:
        try:
            costs = load_cost_config(
                args.costs_venue, args.instrument, path=args.costs_config
            )
        except (ValueError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        print(
            "warning: running frictionless (no spread/slippage/commission). "
            "Pass --costs-venue <venue> to apply standardised cost assumptions.",
            file=sys.stderr,
        )

    try:
        sizing = BacktestSizingConfig(
            initial_capital=args.initial_capital,
            mode=args.sizing_mode,
            fixed_qty=args.fixed_qty,
            risk_per_trade_pct=args.risk_per_trade_pct,
            max_position_qty=args.max_position_qty,
            max_total_exposure=args.max_total_exposure,
            compound=not args.no_compound,
        )
        results = run_backtest(
            strategy_name=args.strategy,
            instrument=args.instrument,
            timeframe=args.timeframe,
            data_dir=args.data_dir,
            param_variants=variants,
            sizing=sizing,
            costs=costs,
        )
    except StrategyParamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not any(r.total_trades for r in results):
        print(
            f"warning: backtest completed but no trades were generated for {args.strategy} "
            f"on {args.instrument} (timeframe={args.timeframe or 'default'}). "
            f"Check that the strategy matches the instrument and that the data window is long enough.",
            file=sys.stderr,
        )

    run_ids: list[int] = []
    if not args.no_history:
        path = args.history_db or str(default_history_path())
        history = BacktestHistory(path)
        request = BacktestRequest(
            strategy_name=args.strategy,
            instrument=args.instrument,
            timeframe=args.timeframe,
            param_variants=variants,
            data_dir=args.data_dir,
            engine="on_bar",
        )
        run_ids = history.record_results(
            results,
            request=request,
            triggered_by="cli",
            notes=args.notes,
        )

    payload = {
        "results": [result.to_dict() for result in results],
        "costs": costs.to_dict() if costs is not None else None,
        "sizing": {
            "initial_capital": sizing.initial_capital,
            "mode": sizing.mode,
            "fixed_qty": sizing.fixed_qty,
            "risk_per_trade_pct": sizing.risk_per_trade_pct,
            "max_position_qty": sizing.max_position_qty,
            "max_total_exposure": sizing.max_total_exposure,
            "compound": sizing.compound,
        },
    }
    if run_ids:
        payload["run_ids"] = run_ids
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
