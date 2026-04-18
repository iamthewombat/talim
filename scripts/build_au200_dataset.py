#!/usr/bin/env python3
"""Build AU200 IG datasets within the default historical-data allowance."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from talim.connectors.pricefeed.ig import IgPriceFeed


_BARS_PER_DAY = {
    "5m": 288,
    "1h": 24,
    "1d": 1,
}

_PROFILES = {
    "backtest-baseline": (
        ("1h", 360, 500),
        ("1d", 730, 500),
    ),
    "execution-warmup": (
        ("5m", 30, 500),
    ),
}


@dataclass(frozen=True, slots=True)
class DatasetSlice:
    timeframe: str
    days: int
    page_size: int

    @property
    def target_bars(self) -> int:
        return self.days * _BARS_PER_DAY[self.timeframe]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", default="AU200.cash")
    parser.add_argument(
        "--profile",
        choices=sorted(_PROFILES),
        default="backtest-baseline",
        help="Dataset slice preset tuned for IG's default historical data allowance.",
    )
    parser.add_argument(
        "--output-root",
        default="data/ig",
        help="Root folder for parquet outputs.",
    )
    parser.add_argument(
        "--manifest",
        help="Optional explicit manifest path. Defaults to <output-root>/<instrument>/dataset-manifest.json",
    )
    return parser


def _write_slice(
    instrument: str,
    output_dir: Path,
    dataset: DatasetSlice,
) -> dict[str, object]:
    feed = IgPriceFeed.from_env(timeframe=dataset.timeframe)
    bars = feed.fetch_recent_bars(
        instrument,
        total_bars=dataset.target_bars,
        page_size=dataset.page_size,
    )
    frame = pd.DataFrame([bar.to_dict() for bar in bars])
    output = output_dir / f"{dataset.timeframe}.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    return {
        "timeframe": dataset.timeframe,
        "days_requested": dataset.days,
        "bars_requested": dataset.target_bars,
        "bars_written": len(frame),
        "path": str(output),
    }


def main() -> int:
    args = _build_parser().parse_args()
    instrument_dir = Path(args.output_root) / args.instrument
    manifest_path = Path(args.manifest) if args.manifest else instrument_dir / "dataset-manifest.json"

    written: list[dict[str, object]] = []
    for timeframe, days, page_size in _PROFILES[args.profile]:
        written.append(
            _write_slice(
                args.instrument,
                instrument_dir,
                DatasetSlice(timeframe=timeframe, days=days, page_size=page_size),
            )
        )

    manifest = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "instrument": args.instrument,
        "profile": args.profile,
        "slices": written,
        "note": (
            "IG historical data uses a weekly allowance budget. "
            "Use backtest-baseline and execution-warmup as separate pulls when needed."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
