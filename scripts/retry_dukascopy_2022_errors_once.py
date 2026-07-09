#!/usr/bin/env python3
"""One-off retry helper for AU200.proxy Dukascopy 2022 fetch-error hours."""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pandas as pd

BASE = Path("data/backtest/dukascopy/AU200.proxy")
SYMBOL = "AUSIDXAUD"
INSTRUMENT = "AU200.proxy"
TIMEFRAME = "5m"
YEAR_PREFIX = "2022"
PRICE_TYPES = ["MID", "BID", "ASK"]


def state_path(price_type: str) -> Path:
    return BASE / f"5m-{price_type.lower()}-download-state.json"


def output_path(price_type: str) -> Path:
    return BASE / f"5m-{price_type.lower()}.parquet"


def manifest_path(price_type: str) -> Path:
    return BASE / f"5m-{price_type.lower()}-manifest.json"


def load_state(price_type: str) -> dict:
    return json.loads(state_path(price_type).read_text())


def group_hours(hours: list[str]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ts = sorted(pd.to_datetime(hours, utc=True))
    if not ts:
        return []
    groups = []
    start = prev = ts[0]
    for item in ts[1:]:
        if item - prev == pd.Timedelta(hours=1):
            prev = item
        else:
            groups.append((start, prev))
            start = prev = item
    groups.append((start, prev))
    return groups


def key(ts: pd.Timestamp) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def cleanup_resolved_fetch_errors(price_type: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int]:
    path = state_path(price_type)
    state = json.loads(path.read_text())
    fetch = dict(state.get("fetch_error_hours", {}))
    before = len(fetch)
    terminal = set(state.get("completed_hours", [])) | set(state.get("empty_hours", [])) | set(state.get("missing_hours", [])) | set(state.get("decode_error_hours", []))
    cursor = start
    while cursor <= end:
        hour_key = key(cursor)
        if hour_key in terminal:
            fetch.pop(hour_key, None)
        cursor += pd.Timedelta(hours=1)
    state["fetch_error_hours"] = dict(sorted(fetch.items()))
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return before, len(fetch)


def main() -> int:
    total_groups = 0
    for price_type in PRICE_TYPES:
        state = load_state(price_type)
        retry_hours = [h for h in state.get("fetch_error_hours", {}) if h.startswith(YEAR_PREFIX)]
        groups = group_hours(retry_hours)
        total_groups += len(groups)
        print(f"=== {price_type}: {len(retry_hours)} fetch-error hours in {len(groups)} groups ===", flush=True)
        for idx, (start, last_hour) in enumerate(groups, 1):
            end_exclusive = last_hour + pd.Timedelta(hours=1)
            print(f"--- {price_type} group {idx}/{len(groups)}: {start} -> {end_exclusive} ---", flush=True)
            cmd = [
                "uv", "run", "python", "scripts/ingest_dukascopy_ticks.py",
                "--symbol", SYMBOL,
                "--instrument", INSTRUMENT,
                "--start", start.isoformat().replace("+00:00", "Z"),
                "--end", end_exclusive.isoformat().replace("+00:00", "Z"),
                "--timeframe", TIMEFRAME,
                "--price-type", price_type,
                "--output", str(output_path(price_type)),
                "--manifest", str(manifest_path(price_type)),
                "--resume-state", str(state_path(price_type)),
                "--append",
                "--no-resume",
                "--timeout-seconds", "30",
                "--sleep-seconds", "0.2",
            ]
            result = subprocess.run(cmd, text=True)
            print(f"--- {price_type} group {idx} exit {result.returncode} ---", flush=True)
            before, after = cleanup_resolved_fetch_errors(price_type, start, last_hour)
            print(f"--- {price_type} fetch_error_hours cleanup: {before} -> {after} ---", flush=True)
            if result.returncode != 0:
                return result.returncode
    print(f"finished retry pass; processed {total_groups} groups", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
