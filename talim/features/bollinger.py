"""Bollinger Band feature materialisation from broker bar data."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from talim.features.rsi import REQUIRED_BAR_COLUMNS
from talim.strategy.indicators import bollinger


def build_bollinger_features(
    bars: pd.DataFrame,
    *,
    period: int = 20,
    num_std: float = 2.0,
    price_type: str = "MID",
    computed_at: datetime | None = None,
) -> pd.DataFrame:
    """Build a wide Bollinger Band feature frame from OHLC bars.

    Bands are calculated from the selected ``price_type`` close series. For CFD
    backtests this is normally ``MID`` for signal generation; execution still
    uses bid/ask from the raw broker bars.
    """

    if period <= 0:
        raise ValueError("period must be positive")
    if num_std <= 0:
        raise ValueError("num_std must be positive")
    missing = REQUIRED_BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")

    selected = bars[bars["price_type"].astype(str).str.upper() == price_type.upper()].copy()
    if selected.empty:
        raise ValueError(f"no {price_type.upper()} bars found")

    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    closes = selected["close"].astype(float).tolist()
    bands = bollinger(closes, period=period, num_std=num_std)
    suffix = f"{period}_{num_std:g}std".replace(".", "p")

    feature = pd.DataFrame(
        {
            "timestamp": selected["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "close_mid": selected["close"].astype(float),
            f"bb_middle_{suffix}": [None if band is None else band.middle for band in bands],
            f"bb_upper_{suffix}": [None if band is None else band.upper for band in bands],
            f"bb_lower_{suffix}": [None if band is None else band.lower for band in bands],
            f"bb_width_{suffix}": [None if band is None else band.upper - band.lower for band in bands],
            f"bb_percent_b_{suffix}": [
                None if band is None or band.upper == band.lower else (close - band.lower) / (band.upper - band.lower)
                for close, band in zip(closes, bands, strict=True)
            ],
        }
    )
    feature["timestamp"] = feature["timestamp"].str.replace(r"\+0000$", "+00:00", regex=True)

    for column in ("instrument", "timeframe", "source"):
        if column in selected.columns:
            feature[column] = selected[column].astype(str).to_numpy()
    feature["basis_price_type"] = price_type.upper()
    feature["computed_at_utc"] = (computed_at or datetime.now(UTC)).isoformat()

    leading = [c for c in ["instrument", "timeframe", "timestamp", "basis_price_type"] if c in feature.columns]
    trailing = [c for c in feature.columns if c not in leading]
    return feature[leading + trailing]
