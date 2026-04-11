"""Shared helpers for the historical-data ingestion CLIs (WP-28).

Both `ingest_databento.py` and `ingest_tardis.py` are CLIs that download
OHLCV bars for a symbol over a date range and write parquet files in the
layout `talim/backtest/data_loader.py` already understands:

    {out_dir}/{symbol}/{YYYY-MM-DD}.parquet

The two scripts share the loop, idempotency check, and parquet writer; the
only thing that differs is the per-day fetcher callable. Tests inject a
fake fetcher so we never hit the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd


REQUIRED_COLS = {"timestamp", "open", "high", "low", "close", "volume"}


@dataclass
class IngestResult:
    written: list[date]
    skipped: list[date]
    failed: list[date]


def daterange(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def _validate(df: pd.DataFrame, day: date) -> pd.DataFrame:
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"{day}: ingest fetcher returned frame missing columns {sorted(missing)}"
        )
    return df


def ingest_range(
    *,
    symbol: str,
    start: date,
    end: date,
    out_dir: Path | str,
    fetch_day: Callable[[str, date], pd.DataFrame],
) -> IngestResult:
    """Walk `start..end` and write one parquet per day under `out_dir/symbol/`.

    Idempotent: days whose parquet already exists are skipped. Days where
    the fetcher returns an empty frame or raises are recorded under `failed`
    and reported at the end so the cron job can be alerted.
    """
    target_dir = Path(out_dir) / symbol
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[date] = []
    skipped: list[date] = []
    failed: list[date] = []

    for day in daterange(start, end):
        out_path = target_dir / f"{day.isoformat()}.parquet"
        if out_path.exists():
            skipped.append(day)
            continue
        try:
            df = fetch_day(symbol, day)
            if df is None or df.empty:
                failed.append(day)
                continue
            df = _validate(df, day)
            df.to_parquet(out_path, index=False)
            written.append(day)
        except Exception:
            failed.append(day)

    return IngestResult(written=written, skipped=skipped, failed=failed)
