"""Support/resistance level table materialisation from broker bar data."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

REQUIRED_LEVEL_COLUMNS = {"timestamp", "high", "low", "close", "price_type"}


def _iso(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%Y-%m-%dT%H:%M:%S%z").str.replace(r"\+0000$", "+00:00", regex=True)


def _touch_metadata(
    selected: pd.DataFrame,
    *,
    level_price: float,
    detected_index: int,
    lookback: int,
    tolerance_points: float,
) -> tuple[int, str | None]:
    start = max(0, detected_index - lookback + 1)
    history = selected.iloc[start : detected_index + 1]
    touched = history[(history["low"] <= level_price + tolerance_points) & (history["high"] >= level_price - tolerance_points)]
    if touched.empty:
        return 0, None
    return len(touched), str(touched["timestamp_iso"].iloc[-1])


def _broken_at(
    selected: pd.DataFrame,
    *,
    level_price: float,
    detected_index: int,
    level_type: str,
    tolerance_points: float,
) -> str | None:
    future = selected.iloc[detected_index + 1 :]
    if level_type == "support":
        broken = future[future["close"] < level_price - tolerance_points]
    else:
        broken = future[future["close"] > level_price + tolerance_points]
    if broken.empty:
        return None
    return str(broken["timestamp_iso"].iloc[0])


def build_levels_table(
    bars: pd.DataFrame,
    *,
    swing_strengths: tuple[int, ...] = (3, 5, 10),
    rolling_windows: tuple[int, ...] = (20, 50, 100),
    price_type: str = "MID",
    tolerance_points: float = 10.0,
    touch_lookback: int = 500,
    computed_at: datetime | None = None,
    include_breaks: bool = True,
    include_touch_metadata: bool = True,
) -> pd.DataFrame:
    """Build a long support/resistance candidate table.

    Swing pivots are timestamped at the bar where the pivot happened, but their
    ``detected_at`` is delayed by ``strength`` bars so downstream feature code
    can avoid look-ahead leakage. Rolling high/low rows are emitted only when
    the rolling level changes, using prior completed bars only.
    """

    if any(strength <= 0 for strength in swing_strengths):
        raise ValueError("swing_strengths must be positive")
    if any(window <= 1 for window in rolling_windows):
        raise ValueError("rolling_windows must be greater than 1")
    if tolerance_points < 0:
        raise ValueError("tolerance_points must be non-negative")
    if touch_lookback <= 0:
        raise ValueError("touch_lookback must be positive")
    missing = REQUIRED_LEVEL_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")

    selected = bars[bars["price_type"].astype(str).str.upper() == price_type.upper()].copy()
    if selected.empty:
        raise ValueError(f"no {price_type.upper()} bars found")

    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
    selected["timestamp_iso"] = _iso(selected["timestamp"])
    for column in ("high", "low", "close"):
        selected[column] = selected[column].astype(float)

    rows: list[dict[str, object]] = []
    computed_at_utc = (computed_at or datetime.now(UTC)).isoformat()
    instrument = str(selected["instrument"].iloc[0]) if "instrument" in selected.columns else ""
    timeframe = str(selected["timeframe"].iloc[0]) if "timeframe" in selected.columns else ""
    source = str(selected["source"].iloc[0]) if "source" in selected.columns else ""

    def add_row(*, level_index: int, detected_index: int, level_price: float, level_type: str, method: str, source_window: int, strength: int) -> None:
        if include_touch_metadata:
            touch_count, last_touched_at = _touch_metadata(
                selected,
                level_price=level_price,
                detected_index=detected_index,
                lookback=touch_lookback,
                tolerance_points=tolerance_points,
            )
        else:
            touch_count, last_touched_at = 0, None
        broken = (
            _broken_at(
                selected,
                level_price=level_price,
                detected_index=detected_index,
                level_type=level_type,
                tolerance_points=tolerance_points,
            )
            if include_breaks
            else None
        )
        rows.append(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "detected_at": str(selected["timestamp_iso"].iloc[detected_index]),
                "level_timestamp": str(selected["timestamp_iso"].iloc[level_index]),
                "level_price": float(level_price),
                "level_type": level_type,
                "method": method,
                "source_window": int(source_window),
                "strength": int(strength),
                "touch_count": int(touch_count),
                "last_touched_at": last_touched_at,
                "broken_at": broken,
                "active": broken is None,
                "break_scan_complete": include_breaks,
                "basis_price_type": price_type.upper(),
                "source": source,
                "computed_at_utc": computed_at_utc,
            }
        )

    highs = selected["high"].tolist()
    lows = selected["low"].tolist()
    n = len(selected)

    for strength in swing_strengths:
        for pivot_index in range(strength, n - strength):
            detected_index = pivot_index + strength
            high_window = highs[pivot_index - strength : pivot_index + strength + 1]
            low_window = lows[pivot_index - strength : pivot_index + strength + 1]
            if highs[pivot_index] == max(high_window):
                add_row(
                    level_index=pivot_index,
                    detected_index=detected_index,
                    level_price=highs[pivot_index],
                    level_type="resistance",
                    method="swing_high",
                    source_window=strength,
                    strength=strength,
                )
            if lows[pivot_index] == min(low_window):
                add_row(
                    level_index=pivot_index,
                    detected_index=detected_index,
                    level_price=lows[pivot_index],
                    level_type="support",
                    method="swing_low",
                    source_window=strength,
                    strength=strength,
                )

    for window in rolling_windows:
        rolling_support = selected["low"].shift(1).rolling(window).min()
        rolling_resistance = selected["high"].shift(1).rolling(window).max()
        support_changes = rolling_support.notna() & rolling_support.ne(rolling_support.shift(1))
        resistance_changes = rolling_resistance.notna() & rolling_resistance.ne(rolling_resistance.shift(1))

        for detected_index, support_price in rolling_support[support_changes].items():
            prior = selected.iloc[detected_index - window : detected_index]
            level_index = int(prior["low"].idxmin())
            add_row(
                level_index=level_index,
                detected_index=int(detected_index),
                level_price=float(support_price),
                level_type="support",
                method="rolling_low",
                source_window=window,
                strength=window,
            )
        for detected_index, resistance_price in rolling_resistance[resistance_changes].items():
            prior = selected.iloc[detected_index - window : detected_index]
            level_index = int(prior["high"].idxmax())
            add_row(
                level_index=level_index,
                detected_index=int(detected_index),
                level_price=float(resistance_price),
                level_type="resistance",
                method="rolling_high",
                source_window=window,
                strength=window,
            )

    levels = pd.DataFrame(rows)
    if levels.empty:
        return pd.DataFrame(
            columns=[
                "instrument",
                "timeframe",
                "detected_at",
                "level_timestamp",
                "level_price",
                "level_type",
                "method",
                "source_window",
                "strength",
                "touch_count",
                "last_touched_at",
                "broken_at",
                "active",
                "break_scan_complete",
                "basis_price_type",
                "source",
                "computed_at_utc",
            ]
        )
    return levels.sort_values(["detected_at", "level_type", "method", "source_window", "level_price"]).reset_index(drop=True)
