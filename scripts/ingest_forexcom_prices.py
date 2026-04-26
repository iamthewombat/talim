#!/usr/bin/env python3
"""Fetch FOREX.com historical bars for a canonical CFD instrument and write Parquet."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from talim.connectors.pricefeed.forexcom import ForexcomCredentials, ForexcomPriceFeed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", required=True, help="Canonical instrument id, e.g. US500.cash")
    parser.add_argument("--timeframe", default="5m", help="Bar timeframe, e.g. 5m or 1h")
    parser.add_argument("--bars", type=int, default=4000, help="Number of bars to fetch (FOREX.com caps at ~4000)")
    parser.add_argument(
        "--output",
        help="Output parquet path. Defaults to data/forexcom/<instrument>/<timeframe>.parquet",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to an existing parquet file and de-duplicate on timestamp",
    )
    return parser


def _default_output(instrument: str, timeframe: str) -> Path:
    safe_instrument = instrument.replace("/", "-")
    return Path("data") / "forexcom" / safe_instrument / f"{timeframe}.parquet"


def main() -> int:
    args = _build_parser().parse_args()
    output = Path(args.output) if args.output else _default_output(args.instrument, args.timeframe)
    output.parent.mkdir(parents=True, exist_ok=True)

    creds = ForexcomCredentials.from_env()
    feed = ForexcomPriceFeed(creds, timeframe=args.timeframe)
    feed.connect()
    try:
        bars = feed.fetch_bars(args.instrument, count=args.bars)
    finally:
        feed.disconnect()

    rows = [bar.to_dict() for bar in bars]
    frame = pd.DataFrame(rows)
    if args.append and output.exists():
        existing = pd.read_parquet(output)
        frame = pd.concat([existing, frame], ignore_index=True)
        frame = frame.drop_duplicates(subset=["timestamp"], keep="last")
        frame = frame.sort_values("timestamp")
    frame.to_parquet(output, index=False)
    print(f"wrote {len(frame)} bars to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
