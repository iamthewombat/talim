"""Nearest support/resistance feature materialisation from level tables."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

REQUIRED_FEATURE_COLUMNS = {"timestamp", "close_mid"}
REQUIRED_LEVEL_COLUMNS = {"detected_at", "level_price", "level_type", "strength", "source_window"}


class _Fenwick:
    def __init__(self, size: int) -> None:
        self.size = size
        self.tree = [0] * (size + 1)

    def add(self, index: int, delta: int) -> None:
        index += 1
        while index <= self.size:
            self.tree[index] += delta
            index += index & -index

    def sum(self, index: int) -> int:
        if index < 0:
            return 0
        index = min(index + 1, self.size)
        total = 0
        while index > 0:
            total += self.tree[index]
            index -= index & -index
        return total

    def total(self) -> int:
        return self.sum(self.size - 1)

    def find_by_order(self, order: int) -> int:
        """Return zero-based index of the 1-based active order."""
        index = 0
        bit = 1 << (self.size.bit_length() - 1)
        while bit:
            nxt = index + bit
            if nxt <= self.size and self.tree[nxt] < order:
                index = nxt
                order -= self.tree[nxt]
            bit >>= 1
        return index


class _ActiveLevels:
    def __init__(self, ticks: np.ndarray) -> None:
        self.ticks = ticks
        self.tree = _Fenwick(len(ticks))
        self.counts = np.zeros(len(ticks), dtype=np.int64)
        self.max_strength = np.zeros(len(ticks), dtype=np.float64)
        self.max_source_window = np.zeros(len(ticks), dtype=np.float64)

    def add_level(self, tick: int, strength: float, source_window: float) -> None:
        index = int(np.searchsorted(self.ticks, tick))
        if index >= len(self.ticks) or self.ticks[index] != tick:
            return
        if self.counts[index] == 0:
            self.tree.add(index, 1)
        self.counts[index] += 1
        self.max_strength[index] = max(self.max_strength[index], float(strength))
        self.max_source_window[index] = max(self.max_source_window[index], float(source_window))

    def nearest_below_or_equal(self, tick: int) -> tuple[float, float, float] | None:
        upper = int(np.searchsorted(self.ticks, tick, side="right") - 1)
        if upper < 0:
            return None
        active_before = self.tree.sum(upper)
        if active_before == 0:
            return None
        index = self.tree.find_by_order(active_before)
        return float(self.ticks[index]), float(self.max_strength[index]), float(self.max_source_window[index])

    def nearest_above_or_equal(self, tick: int) -> tuple[float, float, float] | None:
        lower = int(np.searchsorted(self.ticks, tick, side="left"))
        if lower >= len(self.ticks):
            return None
        active_before = self.tree.sum(lower - 1)
        if active_before == self.tree.total():
            return None
        index = self.tree.find_by_order(active_before + 1)
        return float(self.ticks[index]), float(self.max_strength[index]), float(self.max_source_window[index])


def _iso(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%Y-%m-%dT%H:%M:%S%z").str.replace(r"\+0000$", "+00:00", regex=True)


def build_nearest_level_features(
    features: pd.DataFrame,
    levels: pd.DataFrame,
    *,
    atr_column: str = "atr_14",
    price_scale: float = 10.0,
    computed_at: datetime | None = None,
) -> pd.DataFrame:
    """Build lean numeric nearest support/resistance columns for each bar.

    Only levels with ``detected_at <= timestamp`` are considered, preserving
    backtest causality. The resulting frame is one row per feature/bar row and
    can be merged into the wide feature parquet by timestamp.
    """

    missing_features = REQUIRED_FEATURE_COLUMNS - set(features.columns)
    if missing_features:
        raise ValueError(f"feature frame missing columns: {sorted(missing_features)}")
    missing_levels = REQUIRED_LEVEL_COLUMNS - set(levels.columns)
    if missing_levels:
        raise ValueError(f"levels frame missing columns: {sorted(missing_levels)}")
    if price_scale <= 0:
        raise ValueError("price_scale must be positive")

    bars = features.copy()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars = bars.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
    bars["_close_tick"] = np.rint(bars["close_mid"].astype(float).to_numpy() * price_scale).astype(np.int64)

    candidate_levels = levels.copy()
    candidate_levels["detected_at"] = pd.to_datetime(candidate_levels["detected_at"], utc=True)
    candidate_levels["_level_tick"] = np.rint(candidate_levels["level_price"].astype(float).to_numpy() * price_scale).astype(np.int64)
    candidate_levels = candidate_levels.sort_values("detected_at").reset_index(drop=True)

    support_levels = candidate_levels[candidate_levels["level_type"].astype(str).str.lower() == "support"].reset_index(drop=True)
    resistance_levels = candidate_levels[candidate_levels["level_type"].astype(str).str.lower() == "resistance"].reset_index(drop=True)
    support_active = _ActiveLevels(np.sort(support_levels["_level_tick"].unique()))
    resistance_active = _ActiveLevels(np.sort(resistance_levels["_level_tick"].unique()))

    support_i = 0
    resistance_i = 0
    support_out: list[float] = []
    resistance_out: list[float] = []
    support_strength_out: list[float] = []
    resistance_strength_out: list[float] = []
    support_window_out: list[float] = []
    resistance_window_out: list[float] = []

    support_detected = support_levels["detected_at"].tolist()
    resistance_detected = resistance_levels["detected_at"].tolist()

    for timestamp, close_tick in zip(bars["timestamp"].tolist(), bars["_close_tick"].tolist(), strict=True):
        while support_i < len(support_levels) and support_detected[support_i] <= timestamp:
            row = support_levels.iloc[support_i]
            support_active.add_level(int(row["_level_tick"]), float(row["strength"]), float(row["source_window"]))
            support_i += 1
        while resistance_i < len(resistance_levels) and resistance_detected[resistance_i] <= timestamp:
            row = resistance_levels.iloc[resistance_i]
            resistance_active.add_level(int(row["_level_tick"]), float(row["strength"]), float(row["source_window"]))
            resistance_i += 1

        support = support_active.nearest_below_or_equal(int(close_tick))
        resistance = resistance_active.nearest_above_or_equal(int(close_tick))

        if support is None:
            support_out.append(np.nan)
            support_strength_out.append(np.nan)
            support_window_out.append(np.nan)
        else:
            price_tick, strength, source_window = support
            support_out.append(price_tick / price_scale)
            support_strength_out.append(strength)
            support_window_out.append(source_window)

        if resistance is None:
            resistance_out.append(np.nan)
            resistance_strength_out.append(np.nan)
            resistance_window_out.append(np.nan)
        else:
            price_tick, strength, source_window = resistance
            resistance_out.append(price_tick / price_scale)
            resistance_strength_out.append(strength)
            resistance_window_out.append(source_window)

    result = pd.DataFrame(
        {
            "timestamp": _iso(bars["timestamp"]),
            "nearest_support": support_out,
            "nearest_resistance": resistance_out,
            "support_distance_points": bars["close_mid"].astype(float).to_numpy() - np.array(support_out, dtype=float),
            "resistance_distance_points": np.array(resistance_out, dtype=float) - bars["close_mid"].astype(float).to_numpy(),
            "support_strength": support_strength_out,
            "resistance_strength": resistance_strength_out,
            "support_source_window": support_window_out,
            "resistance_source_window": resistance_window_out,
        }
    )

    if atr_column in bars.columns:
        atr = bars[atr_column].astype(float).replace(0.0, np.nan).to_numpy()
        result["support_distance_atr"] = result["support_distance_points"].to_numpy(dtype=float) / atr
        result["resistance_distance_atr"] = result["resistance_distance_points"].to_numpy(dtype=float) / atr

    result["nearest_levels_computed_at_utc"] = (computed_at or datetime.now(UTC)).isoformat()
    return result
