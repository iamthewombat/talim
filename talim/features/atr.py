"""ATR feature materialisation from broker bar data."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from talim.strategy.indicators import atr_wilder

REQUIRED_ATR_COLUMNS = {"timestamp", "high", "low", "close"}


def build_atr_features(
    bars: pd.DataFrame,
    *,
    period: int = 14,
    price_type: str = "MID",
    computed_at: datetime | None = None,
) -> pd.DataFrame:
    """Build a wide ATR feature frame from OHLC bars.

    ATR is calculated from the selected ``price_type`` high/low/close series.
    For CFD backtests this is normally ``MID`` so volatility features align
    with signal prices while raw bid/ask remains available for execution.
    """

    if period <= 0:
        raise ValueError("period must be positive")
    missing = REQUIRED_ATR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")

    if "price_type" in bars.columns:
        selected = bars[bars["price_type"].astype(str).str.upper() == price_type.upper()].copy()
        basis_price_type = price_type.upper()
        if selected.empty:
            raise ValueError(f"no {price_type.upper()} bars found")
    else:
        selected = bars.copy()
        basis_price_type = "UNSPECIFIED"

    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    feature = pd.DataFrame(
        {
            "timestamp": selected["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            f"atr_{period}": atr_wilder(
                selected["high"].astype(float).tolist(),
                selected["low"].astype(float).tolist(),
                selected["close"].astype(float).tolist(),
                period=period,
            ),
        }
    )
    feature["timestamp"] = feature["timestamp"].str.replace(r"\+0000$", "+00:00", regex=True)

    for column in ("instrument", "timeframe", "source"):
        if column in selected.columns:
            feature[column] = selected[column].astype(str).to_numpy()
    feature["basis_price_type"] = basis_price_type
    feature["computed_at_utc"] = (computed_at or datetime.now(UTC)).isoformat()

    leading = [c for c in ["instrument", "timeframe", "timestamp", "basis_price_type"] if c in feature.columns]
    trailing = [c for c in feature.columns if c not in leading]
    return feature[leading + trailing]
