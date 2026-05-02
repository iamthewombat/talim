from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from talim.features import build_levels_table


def _bars() -> pd.DataFrame:
    highs = [10, 11, 15, 12, 11, 13, 12, 16, 12, 11, 10, 12]
    lows = [8, 7, 9, 8, 6, 8, 7, 9, 6.5, 7, 5, 8]
    closes = [9, 10, 14, 10, 7, 12, 10, 15.5, 8, 8, 6, 11]
    rows = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        ts = (base + timedelta(hours=i)).isoformat()
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "price_type": "MID",
                "source": "forexcom",
            }
        )
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "open": close - 1,
                "high": high - 1,
                "low": low - 1,
                "close": close - 1,
                "price_type": "BID",
                "source": "forexcom",
            }
        )
    return pd.DataFrame(rows)


def test_build_levels_table_detects_swings_after_confirmation_delay():
    levels = build_levels_table(
        _bars(),
        swing_strengths=(1,),
        rolling_windows=(),
        tolerance_points=0.25,
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    high = levels[(levels["method"] == "swing_high") & (levels["level_price"] == 15.0)].iloc[0]
    low = levels[(levels["method"] == "swing_low") & (levels["level_price"] == 6.0)].iloc[0]

    assert high["level_type"] == "resistance"
    assert high["level_timestamp"] == "2026-01-01T02:00:00+00:00"
    assert high["detected_at"] == "2026-01-01T03:00:00+00:00"
    assert high["broken_at"] == "2026-01-01T07:00:00+00:00"
    assert bool(high["active"]) is False
    assert low["level_type"] == "support"
    assert low["detected_at"] == "2026-01-01T05:00:00+00:00"
    assert low["touch_count"] >= 1


def test_build_levels_table_emits_rolling_changes_from_prior_bars_only():
    levels = build_levels_table(
        _bars(),
        swing_strengths=(),
        rolling_windows=(3,),
        tolerance_points=0.25,
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    first_support = levels[(levels["method"] == "rolling_low") & (levels["detected_at"] == "2026-01-01T03:00:00+00:00")].iloc[0]
    first_resistance = levels[(levels["method"] == "rolling_high") & (levels["detected_at"] == "2026-01-01T03:00:00+00:00")].iloc[0]

    assert first_support["level_price"] == pytest.approx(7.0)
    assert first_support["level_timestamp"] == "2026-01-01T01:00:00+00:00"
    assert first_resistance["level_price"] == pytest.approx(15.0)
    assert first_resistance["level_timestamp"] == "2026-01-01T02:00:00+00:00"


def test_build_levels_table_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_levels_table(_bars(), price_type="ASK")
