#!/usr/bin/env python3
"""Retry recorded Dukascopy fetch-error hours for one or more years/price types.

This is a targeted cleanup helper: it does not run full monthly/year pulls. It reads
existing download-state files, groups fetch_error_hours by contiguous hour ranges,
reruns those windows with --no-resume, removes resolved fetch_error entries, and
optionally rewrites coverage summaries.
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
)

DEFAULT_PRICE_TYPES = ["MID", "BID", "ASK"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--years", required=True, help="Comma-separated years or ranges, e.g. 2015,2017-2021")
    p.add_argument("--symbol", default="AUSIDXAUD")
    p.add_argument("--instrument", default="AU200.proxy")
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--price-types", default=",".join(DEFAULT_PRICE_TYPES))
    p.add_argument("--timeout-seconds", default="30")
    p.add_argument("--sleep-seconds", default="0.2")
    p.add_argument("--write-summaries", action="store_true")
    return p.parse_args()


def parse_years(text: str) -> list[int]:
    years: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = [int(x) for x in part.split("-", 1)]
            years.update(range(min(a, b), max(a, b) + 1))
        else:
            years.add(int(part))
    return sorted(years)


def fetch_error_hours_for_year(path: Path, year: int) -> list[str]:
    if not path.exists():
        return []
    state = json.loads(path.read_text())
    prefix = str(year)
    return sorted(h for h in state.get("fetch_error_hours", {}) if h.startswith(prefix))


def run_retry(args: argparse.Namespace, base: Path, price_type: str, year: int, start: pd.Timestamp, last_hour: pd.Timestamp) -> int:
    end_exclusive = last_hour + pd.Timedelta(hours=1)
    cmd = [
        "uv", "run", "python", "scripts/ingest_dukascopy_ticks.py",
        "--symbol", args.symbol,
        "--instrument", args.instrument,
        "--start", iso(start),
        "--end", iso(end_exclusive),
        "--timeframe", args.timeframe,
        "--price-type", price_type,
        "--output", str(output_path(base, args.timeframe, price_type)),
        "--manifest", str(manifest_path(base, args.timeframe, price_type)),
        "--resume-state", str(state_path(base, args.timeframe, price_type)),
        "--append",
        "--no-resume",
        "--timeout-seconds", args.timeout_seconds,
        "--sleep-seconds", args.sleep_seconds,
    ]
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, text=True)
    print(f"exit={result.returncode}", flush=True)
    before, after = cleanup_resolved_fetch_errors(state_path(base, args.timeframe, price_type), start, last_hour)
    print(f"{year} {price_type}: fetch_error cleanup {before} -> {after}", flush=True)
    return result.returncode


def write_summary(base: Path, args: argparse.Namespace, year: int, price_types: list[str]) -> None:
    summary = {
        "year": year,
        "symbol": args.symbol,
        "instrument": args.instrument,
        "timeframe": args.timeframe,
        "summaries": [coverage_summary(base, args.timeframe, p, year) for p in price_types],
    }
    out = base / f"coverage-{year}-summary.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}", flush=True)
    for s in summary["summaries"]:
        print(
            f"SUMMARY {year} {s['price_type']}: rows={s['rows']} "
            f"unresolved={s['unresolved_count']} gaps={s['gap_count']} "
            f"missing_5m={s['missing_5m_total']} range={s['range_start']} -> {s['range_end']}",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    years = parse_years(args.years)
    price_types = [p.strip().upper() for p in args.price_types.split(",") if p.strip()]
    base = base_dir(args.instrument)

    total_groups = 0
    total_hours = 0
    failures = 0
    for year in years:
        for price_type in price_types:
            path = state_path(base, args.timeframe, price_type)
            hours = fetch_error_hours_for_year(path, year)
            groups = group_hours(hours)
            total_groups += len(groups)
            total_hours += len(hours)
            print(f"=== {year} {price_type}: {len(hours)} fetch-error hours in {len(groups)} groups ===", flush=True)
            for idx, (start, last_hour) in enumerate(groups, 1):
                span_hours = int((last_hour - start) / pd.Timedelta(hours=1)) + 1
                print(f"--- {year} {price_type} group {idx}/{len(groups)} ({span_hours}h): {start} -> {last_hour + pd.Timedelta(hours=1)} ---", flush=True)
                rc = run_retry(args, base, price_type, year, start, last_hour)
                if rc != 0:
                    failures += 1

    print(f"finished targeted retry pass; attempted {total_hours} hours across {total_groups} groups; failures={failures}", flush=True)
    if args.write_summaries:
        for year in years:
            write_summary(base, args, year, price_types)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
