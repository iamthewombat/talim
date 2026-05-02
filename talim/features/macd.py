"""MACD feature materialisation from broker bar data."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from talim.features.rsi import REQUIRED_BAR_COLUMNS
from talim.strategy.indicators import macd


def build_macd_features(
    bars: pd.DataFrame,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    price_type: str = "MID",
    computed_at: datetime | None = None,
) -> pd.DataFrame:
    """Build a wide MACD feature frame from OHLC bars.

    MACD is calculated from the selected ``price_type`` close series. For CFD
    backtests this is normally ``MID`` for signal generation; execution still
    uses bid/ask from the raw broker bars.
    """

    if fast_period <= 0:
        raise ValueError("fast_period must be positive")
    if slow_period <= 0:
        raise ValueError("slow_period must be positive")
    if signal_period <= 0:
        raise ValueError("signal_period must be positive")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")
    missing = REQUIRED_BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")

    selected = bars[bars["price_type"].astype(str).str.upper() == price_type.upper()].copy()
    if selected.empty:
        raise ValueError(f"no {price_type.upper()} bars found")

    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    closes = selected["close"].astype(float).tolist()
    values = macd(
        closes,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )
    suffix = f"{fast_period}_{slow_period}_{signal_period}"

    feature = pd.DataFrame(
        {
            "timestamp": selected["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "close_mid": selected["close"].astype(float),
            f"macd_{suffix}": [value.macd for value in values],
            f"macd_signal_{suffix}": [value.signal for value in values],
            f"macd_histogram_{suffix}": [value.histogram for value in values],
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
