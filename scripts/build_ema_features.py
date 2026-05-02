#!/usr/bin/env python3
"""Build EMA feature parquet files from ingested broker bars."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from talim.features import build_ema_features
from talim.features.rsi import merge_feature_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", default="forexcom")
    parser.add_argument("--instrument", required=True, help="Canonical instrument id, e.g. AU200.cash")
    parser.add_argument("--timeframe", action="append", required=True, help="Timeframe to build; may be repeated")
    parser.add_argument("--period", type=int, default=20)
    parser.add_argument("--price-type", default="MID", choices=["MID", "BID", "ASK"])
    parser.add_argument("--data-root", default="data", help="Root containing <venue>/<instrument>/<timeframe>.parquet")
    parser.add_argument("--output-root", default="data/features", help="Root for feature outputs")
    parser.add_argument("--overwrite", action="store_true", help="Replace feature file instead of merging")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    computed_at = datetime.now(UTC)
    written: list[dict[str, object]] = []

    for timeframe in args.timeframe:
        input_path = Path(args.data_root) / args.venue / args.instrument / f"{timeframe}.parquet"
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        output_path = Path(args.output_root) / args.venue / args.instrument / f"{timeframe}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        bars = pd.read_parquet(input_path)
        features = build_ema_features(
            bars,
            period=args.period,
            price_type=args.price_type,
            computed_at=computed_at,
        )
        final = features if args.overwrite else merge_feature_file(features, output_path)
        final.to_parquet(output_path, index=False)
        ema_col = f"ema_{args.period}"
        valid = int(final[ema_col].notna().sum())
        written.append(
            {
                "timeframe": timeframe,
                "path": str(output_path),
                "rows": len(final),
                "valid_ema_rows": valid,
                "first_timestamp": str(final["timestamp"].min()),
                "last_timestamp": str(final["timestamp"].max()),
            }
        )

    for item in written:
        print(
            f"{item['timeframe']}: wrote {item['rows']} rows "
            f"({item['valid_ema_rows']} EMA values) to {item['path']} "
            f"[{item['first_timestamp']} .. {item['last_timestamp']}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
