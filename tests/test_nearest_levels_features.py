from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from talim.features import build_nearest_level_features


def _features() -> pd.DataFrame:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "timestamp": [(base + timedelta(hours=i)).isoformat() for i in range(5)],
            "close_mid": [100.0, 105.0, 107.0, 103.0, 111.0],
            "atr_14": [5.0, 5.0, 4.0, 2.0, 2.0],
        }
    )


def _levels() -> pd.DataFrame:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "detected_at": (base + timedelta(hours=1)).isoformat(),
                "level_price": 102.0,
                "level_type": "support",
                "strength": 3,
                "source_window": 3,
            },
            {
                "detected_at": (base + timedelta(hours=1)).isoformat(),
                "level_price": 110.0,
                "level_type": "resistance",
                "strength": 5,
                "source_window": 5,
            },
            {
                "detected_at": (base + timedelta(hours=3)).isoformat(),
                "level_price": 106.0,
                "level_type": "support",
                "strength": 10,
                "source_window": 10,
            },
            {
                "detected_at": (base + timedelta(hours=4)).isoformat(),
                "level_price": 112.0,
                "level_type": "resistance",
                "strength": 20,
                "source_window": 20,
            },
        ]
    )


def test_build_nearest_level_features_uses_only_detected_historical_levels():
    frame = build_nearest_level_features(
        _features(),
        _levels(),
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert list(frame["nearest_support"]) == pytest.approx([float("nan"), 102.0, 102.0, 102.0, 106.0], nan_ok=True)
    assert list(frame["nearest_resistance"]) == pytest.approx([float("nan"), 110.0, 110.0, 110.0, 112.0], nan_ok=True)
    assert frame["support_distance_points"].iloc[1] == pytest.approx(3.0)
    assert frame["resistance_distance_points"].iloc[1] == pytest.approx(5.0)
    assert frame["support_distance_atr"].iloc[1] == pytest.approx(0.6)
    assert frame["resistance_distance_atr"].iloc[1] == pytest.approx(1.0)
    assert frame["support_strength"].iloc[4] == pytest.approx(10.0)
    assert frame["resistance_source_window"].iloc[4] == pytest.approx(20.0)


def test_build_nearest_level_features_rejects_missing_columns():
    with pytest.raises(ValueError, match="feature frame missing columns"):
        build_nearest_level_features(pd.DataFrame({"timestamp": []}), _levels())
