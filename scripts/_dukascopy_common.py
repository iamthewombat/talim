"""Shared helpers for the Dukascopy pull/retry/coverage scripts.

These scripts are run directly (``uv run python scripts/<name>.py``), so the
scripts directory is on ``sys.path`` and this module is imported as
``_dukascopy_common``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def base_dir(instrument: str) -> Path:
    return Path("data/backtest/dukascopy") / instrument


def state_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}-download-state.json"


def output_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}.parquet"


def manifest_path(base: Path, timeframe: str, price_type: str) -> Path:
    return base / f"{timeframe}-{price_type.lower()}-manifest.json"


def iso(ts: pd.Timestamp) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def group_hours(hours: list[str]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Group ISO hour keys into contiguous (first, last) hour ranges."""
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


def cleanup_resolved_fetch_errors(
    path: Path, start: pd.Timestamp, last_hour: pd.Timestamp
) -> tuple[int, int]:
    """Drop fetch_error entries that a retry moved to a terminal bucket.

    Returns (count before, count after).
    """
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
