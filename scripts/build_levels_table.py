#!/usr/bin/env python3
"""Build support/resistance level parquet tables from ingested broker bars."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from talim.features import build_levels_table


def _csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", default="forexcom")
    parser.add_argument("--instrument", required=True, help="Canonical instrument id, e.g. AU200.cash")
    parser.add_argument("--timeframe", action="append", required=True, help="Timeframe to build; may be repeated")
    parser.add_argument("--swing-strengths", type=_csv_ints, default=(3, 5, 10), help="Comma-separated swing strengths")
    parser.add_argument("--rolling-windows", type=_csv_ints, default=(20, 50, 100), help="Comma-separated rolling windows")
    parser.add_argument("--tolerance-points", type=float, default=10.0)
    parser.add_argument("--touch-lookback", type=int, default=500)
    parser.add_argument("--price-type", default="MID", choices=["MID", "BID", "ASK"])
    parser.add_argument(
        "--include-breaks",
        action="store_true",
        help="Scan future bars to fill broken_at/active-at-dataset-end. Slower; omit for fast research tables.",
    )
    parser.add_argument(
        "--include-touch-metadata",
        action="store_true",
        help="Fill touch_count/last_touched_at. Slower on large intraday tables; omit for fast candidate levels.",
    )
    parser.add_argument("--data-root", default="data", help="Root containing <venue>/<instrument>/<timeframe>.parquet")
    parser.add_argument("--output-root", default="data/levels", help="Root for level table outputs")
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
        levels = build_levels_table(
            bars,
            swing_strengths=args.swing_strengths,
            rolling_windows=args.rolling_windows,
            price_type=args.price_type,
            tolerance_points=args.tolerance_points,
            touch_lookback=args.touch_lookback,
            computed_at=computed_at,
            include_breaks=args.include_breaks,
            include_touch_metadata=args.include_touch_metadata,
        )
        levels.to_parquet(output_path, index=False)
        counts = levels.groupby(["level_type", "method"]).size().to_dict() if not levels.empty else {}
        written.append(
            {
                "timeframe": timeframe,
                "path": str(output_path),
                "rows": len(levels),
                "active_rows": int(levels["active"].sum()) if not levels.empty else 0,
                "first_detected_at": str(levels["detected_at"].min()) if not levels.empty else "",
                "last_detected_at": str(levels["detected_at"].max()) if not levels.empty else "",
                "counts": counts,
            }
        )

    for item in written:
        print(
            f"{item['timeframe']}: wrote {item['rows']} levels "
            f"({item['active_rows']} active at dataset end) to {item['path']} "
            f"[{item['first_detected_at']} .. {item['last_detected_at']}]"
        )
        print(f"  counts: {item['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
