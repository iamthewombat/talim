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


def base_dir(instrument: str) -> Path:
    return Path("data/backtest/dukascopy") / instrument


def state_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}-download-state.json"


def output_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}.parquet"


def manifest_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}-manifest.json"


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, text=True)
    print(f"exit={result.returncode}", flush=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def iso(ts: pd.Timestamp) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def group_hours(hours: list[str]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ts = sorted(pd.to_datetime(hours, utc=True))
    if not ts:
        return []
    groups: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    start = prev = ts[0]
    for item in ts[1:]:
        if item - prev == pd.Timedelta(hours=1):
            prev = item
        else:
            groups.append((start, prev))
            start = prev = item
    groups.append((start, prev))
    return groups


def cleanup_resolved_fetch_errors(path: Path, start: pd.Timestamp, last_hour: pd.Timestamp) -> tuple[int, int]:
    state = json.loads(path.read_text())
    fetch = dict(state.get("fetch_error_hours", {}))
    before = len(fetch)
    terminal = (
        set(state.get("completed_hours", []))
        | set(state.get("empty_hours", []))
        | set(state.get("missing_hours", []))
        | set(state.get("decode_error_hours", []))
    )
    cursor = start
    while cursor <= last_hour:
        hour_key = iso(cursor)
        if hour_key in terminal:
            fetch.pop(hour_key, None)
        cursor += pd.Timedelta(hours=1)
    state["fetch_error_hours"] = dict(sorted(fetch.items()))
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return before, len(fetch)


def month_bounds(year: int):
    for month in range(1, 13):
        start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        end = start + pd.DateOffset(months=1)
        yield start, pd.Timestamp(end)


def unresolved_for_year(path: Path, year: int) -> list[str]:
    if not path.exists():
        return []
    state = json.loads(path.read_text())
    prefix = str(year)
    return sorted(
        h
        for h in list(state.get("fetch_error_hours", {}).keys())
        + state.get("missing_hours", [])
        + state.get("decode_error_hours", [])
        if h.startswith(prefix)
    )


def coverage_summary(base: Path, timeframe: str, price_type: str, year: int) -> dict:
    start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
    end = pd.Timestamp(f"{year + 1}-01-01T00:00:00Z")
    path = output_path(base, timeframe, price_type)
    df = pd.read_parquet(path, columns=["timestamp"])
    ts = pd.Series(pd.to_datetime(df["timestamp"], utc=True)).sort_values().drop_duplicates()
    ts = ts[(ts >= start) & (ts < end)].reset_index(drop=True)
    gaps = []
    for i, delta in enumerate(ts.diff()):
        if pd.isna(delta) or delta <= pd.Timedelta(minutes=5):
            continue
        gap_start = ts.iloc[i - 1] + pd.Timedelta(minutes=5)
        gap_end = ts.iloc[i] - pd.Timedelta(minutes=5)
        missing = int(delta / pd.Timedelta(minutes=5)) - 1
        gaps.append({"start": str(gap_start), "end": str(gap_end), "missing_5m": missing})
    unresolved = unresolved_for_year(state_path(base, timeframe, price_type), year)
    unresolved_groups = [
        {"start": str(a), "end": str(b), "hours": int((b - a) / pd.Timedelta(hours=1)) + 1}
        for a, b in group_hours(unresolved)
    ]
    return {
        "price_type": price_type,
        "rows": int(len(ts)),
        "range_start": str(ts.iloc[0]) if len(ts) else None,
        "range_end": str(ts.iloc[-1]) if len(ts) else None,
        "gap_count": len(gaps),
        "missing_5m_total": int(sum(g["missing_5m"] for g in gaps)),
        "largest_gaps": sorted(gaps, key=lambda g: g["missing_5m"], reverse=True)[:10],
        "unresolved_count": len(unresolved),
        "unresolved_groups": unresolved_groups,
    }


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

        # Retry recorded 2023 transient/problem hours. Recompute groups between passes because
        # successful retries are removed from fetch_error_hours during cleanup.
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
