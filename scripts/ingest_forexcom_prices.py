#!/usr/bin/env python3
"""Fetch FOREX.com historical bars for a canonical CFD instrument and write Parquet."""

from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from talim.connectors.pricefeed.forexcom import ForexcomCredentials, ForexcomPriceFeed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", required=True, help="Canonical instrument id, e.g. US500.cash")
    parser.add_argument("--timeframe", default="5m", help="Bar timeframe, e.g. 5m or 1h")
    parser.add_argument("--bars", type=int, default=4000, help="Number of latest bars to fetch when no date range is supplied")
    parser.add_argument("--start", help="UTC start date/time, e.g. 2025-12-30 or 2025-12-30T00:00:00Z")
    parser.add_argument("--end", help="UTC end date/time. Defaults to now when --start/--months is supplied")
    parser.add_argument("--months", type=int, help="Fetch approximately this many months back from --end/now")
    parser.add_argument("--chunk-size", type=int, default=4000, help="Bars per paged request; max 4000")
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Delay between paged requests")
    parser.add_argument("--price-type", default="MID", choices=["ASK", "BID", "MID"], help="FOREX.com price type")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv file to load before reading credentials")
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


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" not in text and len(text) == 10:
        text = text + "T00:00:00+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _frame_from_bars(bars: list, *, price_type: str) -> pd.DataFrame:
    rows = []
    fetched_at = datetime.now(UTC).isoformat()
    for bar in bars:
        row = bar.to_dict()
        row["price_type"] = price_type.upper()
        row["source"] = "forexcom"
        row["fetched_at_utc"] = fetched_at
        rows.append(row)
    return pd.DataFrame(rows)


def _merge_existing(frame: pd.DataFrame, output: Path, *, append: bool) -> pd.DataFrame:
    if append and output.exists():
        existing = pd.read_parquet(output)
        frame = pd.concat([existing, frame], ignore_index=True)
    if frame.empty:
        return frame
    frame = frame.drop_duplicates(subset=["timestamp", "price_type"], keep="last")
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def _fetch_range(feed: ForexcomPriceFeed, instrument: str, *, start: datetime, end: datetime, chunk_size: int, sleep_seconds: float, price_type: str) -> list:
    all_bars = []
    cursor = int(end.timestamp())
    start_ts = start.timestamp()
    request_no = 0

    while True:
        request_no += 1
        bars = feed.fetch_bars_before(
            instrument,
            to_timestamp_utc=cursor,
            count=chunk_size,
            price_type=price_type,
        )
        if not bars:
            print(f"request {request_no}: no bars returned; stopping")
            break

        in_range = [bar for bar in bars if start <= bar.timestamp <= end]
        all_bars.extend(in_range)
        earliest = bars[0].timestamp
        latest = bars[-1].timestamp
        print(
            f"request {request_no}: got {len(bars)} bars ({earliest.isoformat()} .. {latest.isoformat()}), "
            f"kept {len(in_range)}"
        )

        if earliest.timestamp() <= start_ts:
            break
        next_cursor = int(earliest.timestamp())
        if next_cursor >= cursor:
            print(
                "request paging stopped: FOREX.com did not return data before "
                f"{earliest.isoformat()}"
            )
            break
        cursor = next_cursor
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return all_bars


def main() -> int:
    args = _build_parser().parse_args()
    _load_dotenv(Path(args.env_file))

    output = Path(args.output) if args.output else _default_output(args.instrument, args.timeframe)
    output.parent.mkdir(parents=True, exist_ok=True)

    creds = ForexcomCredentials.from_env()
    feed = ForexcomPriceFeed(creds, timeframe=args.timeframe)
    feed.connect()
    try:
        end = _parse_utc(args.end) if args.end else datetime.now(UTC)
        if args.start or args.months:
            start = _parse_utc(args.start) if args.start else end - timedelta(days=31 * args.months)
            if start >= end:
                raise ValueError("--start must be before --end")
            bars = _fetch_range(
                feed,
                args.instrument,
                start=start,
                end=end,
                chunk_size=min(max(1, args.chunk_size), 4000),
                sleep_seconds=args.sleep_seconds,
                price_type=args.price_type,
            )
        else:
            bars = feed.fetch_bars(args.instrument, count=args.bars)
    finally:
        feed.disconnect()

    frame = _frame_from_bars(bars, price_type=args.price_type)
    frame = _merge_existing(frame, output, append=args.append)
    frame.to_parquet(output, index=False)
    if frame.empty:
        print(f"wrote 0 bars to {output}")
    else:
        print(
            f"wrote {len(frame)} bars to {output} "
            f"({frame['timestamp'].min()} .. {frame['timestamp'].max()})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
