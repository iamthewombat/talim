#!/usr/bin/env python3
"""Pull one Dukascopy proxy year, retry transient fetch gaps, and summarize coverage.

Designed for AU200.proxy historical-data backfills where market closures are expected
but fetch_error/missing/decode entries should be retried and reported.
"""
from __future__ import annotations

import argparse
import json
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
import ingest_dukascopy_ticks as ingest

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
    p.add_argument("--max-fetch-retries", type=int, default=3)
    p.add_argument("--backoff-base-seconds", type=float, default=2.0)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--raw-cache-dir", default="data/cache/dukascopy/bi5")
    p.add_argument("--no-raw-cache", action="store_true")
    p.add_argument("--include-market-closures", action="store_true")
    p.add_argument("--skip-month-pull", action="store_true", help="Only retry recorded unresolved hours")
    p.add_argument("--summary-output", required=True)
    return p.parse_args()


def run_ingest_window(
    args: argparse.Namespace,
    *,
    price_type: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    no_resume: bool = False,
) -> None:
    base = base_dir(args.instrument)
    ingest_args = argparse.Namespace(
        symbol=args.symbol,
        instrument=args.instrument,
        start=iso(start),
        end=iso(end),
        timeframe=args.timeframe,
        price_scale="auto",
        price_type=price_type,
        source="dukascopy",
        sleep_seconds=float(args.sleep_seconds),
        timeout_seconds=float(args.timeout_seconds),
        max_fetch_retries=args.max_fetch_retries,
        backoff_base_seconds=args.backoff_base_seconds,
        workers=args.workers,
        raw_cache_dir=args.raw_cache_dir,
        no_raw_cache=args.no_raw_cache,
        include_market_closures=args.include_market_closures,
        output=str(output_path(base, args.timeframe, price_type)),
        append=True,
        overwrite=False,
        manifest=str(manifest_path(base, args.timeframe, price_type)),
        resume_state=str(state_path(base, args.timeframe, price_type)),
        no_resume=no_resume,
    )
    print(
        "$ ingest_dukascopy_ticks "
        f"--symbol {args.symbol} --instrument {args.instrument} "
        f"--start {ingest_args.start} --end {ingest_args.end} "
        f"--timeframe {args.timeframe} --price-type {price_type} "
        f"--workers {args.workers}",
        flush=True,
    )
    rc = ingest.run_ingest(ingest_args)
    print(f"exit={rc}", flush=True)
    if rc != 0:
        raise SystemExit(rc)


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
        if args.skip_month_pull:
            print(f"=== Skipping monthly pull for {args.instrument} {args.year} {price_type} ===", flush=True)
        else:
            print(f"=== Pulling {args.instrument} {args.year} {price_type} ===", flush=True)
            for start, end in month_bounds(args.year):
                print(f"--- {price_type} {start:%Y-%m} ---", flush=True)
                run_ingest_window(args, price_type=price_type, start=start, end=end)

        # Retry recorded transient/problem hours for the requested year. Recompute
        # groups between passes because successful retries are removed from
        # fetch_error_hours during cleanup.
        print(f"=== Retrying unresolved {args.year} hours for {price_type} ===", flush=True)
        groups = group_hours(unresolved_for_year(state_path(base, args.timeframe, price_type), args.year))
        print(f"{price_type}: {len(groups)} groups before retry", flush=True)
        for idx, (start, last_hour) in enumerate(groups, 1):
            end = last_hour + pd.Timedelta(hours=1)
            print(f"--- retry {price_type} group {idx}/{len(groups)}: {start} -> {end} ---", flush=True)
            run_ingest_window(args, price_type=price_type, start=start, end=end, no_resume=True)
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
