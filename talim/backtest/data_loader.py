"""OHLCV data loader for backtests (WP-12).

Loads bars from a directory of parquet files. Supported layouts:

  1. Per-day files:  {data_dir}/{instrument}/{YYYY-MM-DD}.parquet
  2. Single file:    {data_dir}/{instrument}.parquet  (filtered by date column)

Bars must have columns: timestamp, open, high, low, close, volume.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


REQUIRED_COLS = {"timestamp", "open", "high", "low", "close", "volume"}


def _validate(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {sorted(missing)}")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def load_ohlcv(
    data_dir: str | Path,
    instrument: str,
    matched_dates: list[date] | None = None,
) -> pd.DataFrame:
    """Load OHLCV bars for `instrument`, optionally filtered to `matched_dates`."""
    root = Path(data_dir)
    per_day_dir = root / instrument
    if per_day_dir.is_dir():
        if matched_dates:
            files = [per_day_dir / f"{d.isoformat()}.parquet" for d in matched_dates]
            files = [f for f in files if f.exists()]
        else:
            files = sorted(per_day_dir.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(
                f"No parquet files found for {instrument} under {per_day_dir}"
            )
        frames = [pd.read_parquet(f) for f in files]
        return _validate(pd.concat(frames, ignore_index=True))

    single = root / f"{instrument}.parquet"
    if single.exists():
        df = _validate(pd.read_parquet(single))
        if matched_dates:
            wanted = {d for d in matched_dates}
            df = df[df["timestamp"].dt.date.isin(wanted)].reset_index(drop=True)
        return df

    raise FileNotFoundError(
        f"No data found for {instrument} in {root} (looked for {per_day_dir} and {single})"
    )


def load_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise an in-memory frame (used by tests)."""
    return _validate(df)
