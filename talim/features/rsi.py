"""RSI feature materialisation from broker bar data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from talim.strategy.indicators import rsi_wilder

REQUIRED_BAR_COLUMNS = {"timestamp", "close", "price_type"}


def build_rsi_features(
    bars: pd.DataFrame,
    *,
    period: int = 14,
    price_type: str = "MID",
    computed_at: datetime | None = None,
) -> pd.DataFrame:
    """Build a wide RSI feature frame from OHLC bars.

    RSI is calculated from the selected ``price_type`` close series. For our CFD
    backtests this is normally ``MID``: signals use mid prices, while execution
    uses bid/ask from the raw bar files.
    """

    if period <= 0:
        raise ValueError("period must be positive")
    missing = REQUIRED_BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")

    selected = bars[bars["price_type"].astype(str).str.upper() == price_type.upper()].copy()
    if selected.empty:
        raise ValueError(f"no {price_type.upper()} bars found")

    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    feature = pd.DataFrame(
        {
            "timestamp": selected["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "close_mid": selected["close"].astype(float),
            f"rsi_{period}": rsi_wilder(selected["close"].astype(float).tolist(), period=period),
        }
    )
    # Normalise +0000 to the ISO style already used by bar.to_dict().
    feature["timestamp"] = feature["timestamp"].str.replace(r"\+0000$", "+00:00", regex=True)

    for column in ("instrument", "timeframe", "source"):
        if column in selected.columns:
            feature[column] = selected[column].astype(str).to_numpy()
    feature["basis_price_type"] = price_type.upper()
    feature["computed_at_utc"] = (computed_at or datetime.now(UTC)).isoformat()

    leading = [c for c in ["instrument", "timeframe", "timestamp", "basis_price_type"] if c in feature.columns]
    trailing = [c for c in feature.columns if c not in leading]
    return feature[leading + trailing]


def merge_feature_file(new_features: pd.DataFrame, output: str | Path) -> pd.DataFrame:
    """Merge features into an existing wide feature parquet by timestamp.

    This lets later indicators add columns without destroying existing feature
    columns. New columns/values win on overlap.
    """

    output = Path(output)
    if output.exists():
        existing = pd.read_parquet(output)
        merged = existing.merge(
            new_features,
            on="timestamp",
            how="outer",
            suffixes=("", "__new"),
        )
        for col in list(merged.columns):
            if not col.endswith("__new"):
                continue
            base = col.removesuffix("__new")
            if base in merged.columns:
                merged[base] = merged[col].combine_first(merged[base])
                merged = merged.drop(columns=[col])
            else:
                merged = merged.rename(columns={col: base})
    else:
        merged = new_features.copy()

    merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
    merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    merged["timestamp"] = merged["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z").str.replace(
        r"\+0000$", "+00:00", regex=True
    )
    return merged.reset_index(drop=True)
