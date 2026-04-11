"""Build and update the regime fingerprint library from OHLCV data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from talim.regime.fingerprint import compute_fingerprint


def _split_into_sessions(
    df: pd.DataFrame, session_size: int = 50
) -> list[tuple[date, pd.DataFrame]]:
    """Split a DataFrame into non-overlapping sessions of `session_size` bars.

    Returns list of (session_date, session_df) tuples.
    """
    sessions = []
    for start in range(0, len(df) - session_size + 1, session_size):
        chunk = df.iloc[start : start + session_size].copy()
        # Use the date of the first bar in the session
        if "timestamp" in chunk.columns:
            session_date = pd.Timestamp(chunk["timestamp"].iloc[0]).date()
        else:
            session_date = date(2000, 1, 1)  # fallback
        sessions.append((session_date, chunk))
    return sessions


def build_library(
    df: pd.DataFrame, session_size: int = 50
) -> tuple[np.ndarray, list[date]]:
    """Build a fingerprint library from an OHLCV DataFrame.

    Args:
        df: DataFrame with columns [open, high, low, close, volume] and
            optionally [timestamp].
        session_size: Number of bars per session window.

    Returns:
        (features, dates) where features is shape (n_sessions, 6)
        and dates is a list of session dates.
    """
    sessions = _split_into_sessions(df, session_size)
    if not sessions:
        return np.empty((0, 6), dtype=np.float64), []

    features = []
    dates = []
    for session_date, session_df in sessions:
        fp = compute_fingerprint(session_df)
        features.append(fp)
        dates.append(session_date)

    return np.array(features, dtype=np.float64), dates


def update_library(
    existing_features: np.ndarray,
    existing_dates: list[date],
    new_df: pd.DataFrame,
    session_size: int = 50,
) -> tuple[np.ndarray, list[date]]:
    """Append new sessions to an existing library.

    Returns the combined (features, dates).
    """
    new_features, new_dates = build_library(new_df, session_size)
    if new_features.shape[0] == 0:
        return existing_features, existing_dates

    if existing_features.shape[0] == 0:
        return new_features, new_dates

    combined_features = np.vstack([existing_features, new_features])
    combined_dates = existing_dates + new_dates
    return combined_features, combined_dates
