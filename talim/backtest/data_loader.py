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
    if "price_type" in df.columns:
        price_types = {str(value).upper() for value in df["price_type"].dropna().unique()}
        if len(price_types) > 1:
            if "MID" not in price_types:
                raise ValueError(
                    "OHLCV frame contains multiple price_type values but no MID rows "
                    f"to use for signal backtests: {sorted(price_types)}"
                )
            df = df[df["price_type"].astype(str).str.upper() == "MID"].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].duplicated().any():
        duplicate_count = int(df["timestamp"].duplicated().sum())
        raise ValueError(
            f"OHLCV frame contains {duplicate_count} duplicate timestamp rows after price_type filtering"
        )
    return df.sort_values("timestamp").reset_index(drop=True)


def load_ohlcv(
    data_dir: str | Path,
    instrument: str,
    matched_dates: list[date] | None = None,
    timeframe: str | None = None,
) -> pd.DataFrame:
    """Load OHLCV bars for `instrument`, optionally filtered to `matched_dates`.

    Fails loudly on missing data: if an explicit `timeframe` is requested but
    the corresponding parquet file is absent, a FileNotFoundError is raised
    rather than silently falling back to a different resolution. An empty
    resulting frame also raises, so backtests never report zero-trade results
    that are actually zero-bar runs.
    """
    root = Path(data_dir)
    per_day_dir = root / instrument
    if per_day_dir.is_dir():
        if timeframe:
            timeframe_file = per_day_dir / f"{timeframe}.parquet"
            if not timeframe_file.exists():
                raise FileNotFoundError(
                    f"No {timeframe} parquet for {instrument} at {timeframe_file}. "
                    f"Ingest via scripts/ingest_ig_prices.py, "
                    f"scripts/ingest_forexcom_prices.py, or "
                    f"scripts/ingest_dukascopy_ticks.py before running this backtest."
                )
            df = _validate(pd.read_parquet(timeframe_file))
            if df.empty:
                raise ValueError(
                    f"Parquet file {timeframe_file} is empty; ingest failed or data is missing."
                )
            return df
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
        df = _validate(pd.concat(frames, ignore_index=True))
        if df.empty:
            raise ValueError(
                f"All parquet files under {per_day_dir} are empty after filtering."
            )
        return df

    single = root / f"{instrument}.parquet"
    if single.exists():
        df = _validate(pd.read_parquet(single))
        if matched_dates:
            wanted = {d for d in matched_dates}
            df = df[df["timestamp"].dt.date.isin(wanted)].reset_index(drop=True)
        if df.empty:
            raise ValueError(
                f"{single} resolved to zero rows after filtering by matched_dates."
            )
        return df

    raise FileNotFoundError(
        f"No data found for {instrument} in {root} (looked for {per_day_dir} and {single})"
    )


def load_quotes(
    data_dir: str | Path,
    instrument: str,
    timeframe: str,
) -> pd.DataFrame:
    """Load per-bar BID/ASK closes for per-bar cost modelling.

    Reads the same canonical parquet as `load_ohlcv` but keeps the BID and
    ASK rows, returning columns: timestamp, bid_close, ask_close. Fails
    loudly when the file has no bid/ask rows so a mid-only dataset cannot
    silently produce frictionless per-bar fills.
    """
    path = Path(data_dir) / instrument / f"{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No {timeframe} parquet for {instrument} at {path}; per-bar costs "
            "need the canonical multi-price_type file."
        )
    df = pd.read_parquet(path)
    if "price_type" not in df.columns:
        raise ValueError(f"{path} has no price_type column; cannot extract bid/ask quotes")
    pt = df["price_type"].astype(str).str.upper()
    bid = df[pt == "BID"][["timestamp", "close"]].rename(columns={"close": "bid_close"})
    ask = df[pt == "ASK"][["timestamp", "close"]].rename(columns={"close": "ask_close"})
    if bid.empty or ask.empty:
        raise ValueError(
            f"{path} lacks BID and/or ASK rows "
            f"(bid={len(bid)}, ask={len(ask)}); cannot build per-bar costs"
        )
    quotes = bid.merge(ask, on="timestamp", how="inner")
    quotes["timestamp"] = pd.to_datetime(quotes["timestamp"])
    quotes = quotes.sort_values("timestamp").reset_index(drop=True)
    spread = quotes["ask_close"] - quotes["bid_close"]
    quotes = quotes[(spread >= 0) & (spread < quotes["bid_close"] * 0.01)]
    return quotes.reset_index(drop=True)


def load_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise an in-memory frame (used by tests)."""
    return _validate(df)
