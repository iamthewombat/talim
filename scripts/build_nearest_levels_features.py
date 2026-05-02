#!/usr/bin/env python3
"""Build lean nearest support/resistance columns into feature parquets."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from talim.features import build_nearest_level_features
from talim.features.rsi import merge_feature_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", default="forexcom")
    parser.add_argument("--instrument", required=True, help="Canonical instrument id, e.g. AU200.cash")
    parser.add_argument("--timeframe", action="append", required=True, help="Timeframe to build; may be repeated")
    parser.add_argument("--feature-root", default="data/features", help="Root containing feature parquet files")
    parser.add_argument("--levels-root", default="data/levels", help="Root containing level parquet files")
    parser.add_argument("--output-root", default="data/features", help="Root for merged feature outputs")
    parser.add_argument("--atr-column", default="atr_14")
    parser.add_argument("--price-scale", type=float, default=10.0, help="AU200 tick scale; 10 keeps one decimal point")
    parser.add_argument("--overwrite", action="store_true", help="Replace output with nearest-level columns instead of merging")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    computed_at = datetime.now(UTC)
    written: list[dict[str, object]] = []

    for timeframe in args.timeframe:
        feature_path = Path(args.feature_root) / args.venue / args.instrument / f"{timeframe}.parquet"
        levels_path = Path(args.levels_root) / args.venue / args.instrument / f"{timeframe}.parquet"
        if not feature_path.exists():
            raise FileNotFoundError(feature_path)
        if not levels_path.exists():
            raise FileNotFoundError(levels_path)
        output_path = Path(args.output_root) / args.venue / args.instrument / f"{timeframe}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        features = pd.read_parquet(feature_path)
        levels = pd.read_parquet(levels_path)
        nearest = build_nearest_level_features(
            features,
            levels,
            atr_column=args.atr_column,
            price_scale=args.price_scale,
            computed_at=computed_at,
        )
        final = nearest if args.overwrite else merge_feature_file(nearest, output_path)
        final.to_parquet(output_path, index=False)
        support_valid = int(final["nearest_support"].notna().sum())
        resistance_valid = int(final["nearest_resistance"].notna().sum())
        written.append(
            {
                "timeframe": timeframe,
                "path": str(output_path),
                "rows": len(final),
                "support_valid": support_valid,
                "resistance_valid": resistance_valid,
                "first_timestamp": str(final["timestamp"].min()),
                "last_timestamp": str(final["timestamp"].max()),
            }
        )

    for item in written:
        print(
            f"{item['timeframe']}: wrote {item['rows']} rows "
            f"({item['support_valid']} support, {item['resistance_valid']} resistance) to {item['path']} "
            f"[{item['first_timestamp']} .. {item['last_timestamp']}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
