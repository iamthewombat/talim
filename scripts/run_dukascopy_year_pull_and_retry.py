#!/usr/bin/env python3
"""Pull one Dukascopy proxy year, retry transient fetch gaps, and summarize coverage.

Designed for AU200.proxy historical-data backfills where market closures are expected
but fetch_error/missing/decode entries should be retried and reported.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd

from _dukascopy_common import (
    base_dir,
    cleanup_resolved_fetch_errors,
    coverage_summary,
    group_hours,
    iso,
    manifest_path,
    output_path,
    state_path,
    unresolved_for_year,
)

PRICE_TYPES_DEFAULT = ["MID", "BID", "ASK"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--symbol", default="AUSIDXAUD")
    p.add_argument("--instrument", default="AU200.proxy")
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--price-types", default=",".join(PRICE_TYPES_DEFAULT))
    p.add_argument("--timeout-seconds", default="30")
    p.add_argument("--sleep-seconds", default="0.2")
    p.add_argument("--summary-output", required=True)
    return p.parse_args()


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, text=True)
    print(f"exit={result.returncode}", flush=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def month_bounds(year: int):
    for month in range(1, 13):
        start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        end = start + pd.DateOffset(months=1)
        yield start, pd.Timestamp(end)


def main() -> int:
    args = parse_args()
    price_types = [p.strip().upper() for p in args.price_types.split(",") if p.strip()]
    base = base_dir(args.instrument)
    base.mkdir(parents=True, exist_ok=True)

    for price_type in price_types:
        print(f"=== Pulling {args.instrument} {args.year} {price_type} ===", flush=True)
        for start, end in month_bounds(args.year):
            print(f"--- {price_type} {start:%Y-%m} ---", flush=True)
            run([
                "uv", "run", "python", "scripts/ingest_dukascopy_ticks.py",
                "--symbol", args.symbol,
                "--instrument", args.instrument,
                "--start", iso(start),
                "--end", iso(end),
                "--timeframe", args.timeframe,
                "--price-type", price_type,
                "--output", str(output_path(base, args.timeframe, price_type)),
                "--manifest", str(manifest_path(base, args.timeframe, price_type)),
                "--resume-state", str(state_path(base, args.timeframe, price_type)),
                "--append",
                "--timeout-seconds", args.timeout_seconds,
                "--sleep-seconds", args.sleep_seconds,
            ])

        # Retry recorded transient/problem hours for the requested year. Recompute
        # groups between passes because successful retries are removed from
        # fetch_error_hours during cleanup.
        print(f"=== Retrying unresolved {args.year} hours for {price_type} ===", flush=True)
        groups = group_hours(unresolved_for_year(state_path(base, args.timeframe, price_type), args.year))
        print(f"{price_type}: {len(groups)} groups before retry", flush=True)
        for idx, (start, last_hour) in enumerate(groups, 1):
            end = last_hour + pd.Timedelta(hours=1)
            print(f"--- retry {price_type} group {idx}/{len(groups)}: {start} -> {end} ---", flush=True)
            run([
                "uv", "run", "python", "scripts/ingest_dukascopy_ticks.py",
                "--symbol", args.symbol,
                "--instrument", args.instrument,
                "--start", iso(start),
                "--end", iso(end),
                "--timeframe", args.timeframe,
                "--price-type", price_type,
                "--output", str(output_path(base, args.timeframe, price_type)),
                "--manifest", str(manifest_path(base, args.timeframe, price_type)),
                "--resume-state", str(state_path(base, args.timeframe, price_type)),
                "--append",
                "--no-resume",
                "--timeout-seconds", args.timeout_seconds,
                "--sleep-seconds", args.sleep_seconds,
            ])
            before, after = cleanup_resolved_fetch_errors(state_path(base, args.timeframe, price_type), start, last_hour)
            print(f"{price_type}: fetch_error cleanup {before} -> {after}", flush=True)

    summary = {
        "year": args.year,
        "symbol": args.symbol,
        "instrument": args.instrument,
        "timeframe": args.timeframe,
        "summaries": [coverage_summary(base, args.timeframe, p, args.year) for p in price_types],
    }
    out = Path(args.summary_output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"wrote summary to {out}", flush=True)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
