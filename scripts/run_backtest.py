#!/usr/bin/env python3
"""Run a Talim backtest from the command line and print JSON results."""

from __future__ import annotations

import argparse
import json

from talim.backtest.engine import run_backtest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, help="Strategy name, e.g. momentum-AU200")
    parser.add_argument("--instrument", default="ES", help="Instrument id, e.g. AU200.cash")
    parser.add_argument("--timeframe", help="Optional timeframe-specific parquet file, e.g. 1h")
    parser.add_argument("--data-dir", default="data", help="Root data directory")
    parser.add_argument(
        "--params",
        action="append",
        default=[],
        help='JSON param variant. Repeat to run multiple variants, e.g. --params \'{"ema_fast_period":10}\'',
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    variants = [json.loads(item) for item in args.params] or [{}]
    results = run_backtest(
        strategy_name=args.strategy,
        instrument=args.instrument,
        timeframe=args.timeframe,
        data_dir=args.data_dir,
        param_variants=variants,
    )
    print(json.dumps([result.to_dict() for result in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
