#!/usr/bin/env python3
"""Run a Talim backtest from the command line and print JSON results."""

from __future__ import annotations

import argparse
import json
import sys

from talim.backtest.engine import run_backtest
from talim.backtest.history import BacktestHistory, default_history_path
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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        variants = [json.loads(item) for item in args.params] or [{}]
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in --params: {exc}", file=sys.stderr)
        return 2

    try:
        results = run_backtest(
            strategy_name=args.strategy,
            instrument=args.instrument,
            timeframe=args.timeframe,
            data_dir=args.data_dir,
            param_variants=variants,
        )
    except StrategyParamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
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
    }
    if run_ids:
        payload["run_ids"] = run_ids
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
