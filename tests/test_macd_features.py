from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from talim.features import build_macd_features
from talim.strategy.indicators import macd


def _bars() -> pd.DataFrame:
    rows = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(35):
        ts = (base + timedelta(hours=i)).isoformat()
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "close": 100.0 + i,
                "price_type": "MID",
                "source": "forexcom",
            }
        )
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "close": 99.0 + i,
                "price_type": "BID",
                "source": "forexcom",
            }
        )
    return pd.DataFrame(rows)


def test_build_macd_features_uses_mid_close_and_existing_indicator():
    frame = build_macd_features(
        _bars(),
        fast_period=12,
        slow_period=26,
        signal_period=9,
        price_type="MID",
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert list(frame.columns) == [
        "instrument",
        "timeframe",
        "timestamp",
        "basis_price_type",
        "close_mid",
        "macd_12_26_9",
        "macd_signal_12_26_9",
        "macd_histogram_12_26_9",
        "source",
        "computed_at_utc",
    ]
    assert len(frame) == 35
    assert frame["basis_price_type"].unique().tolist() == ["MID"]
    closes = [100.0 + i for i in range(35)]
    expected = macd(closes, fast_period=12, slow_period=26, signal_period=9)
    assert frame["macd_12_26_9"].tolist() == pytest.approx([v.macd for v in expected])
    assert frame["macd_signal_12_26_9"].tolist() == pytest.approx([v.signal for v in expected])
    assert frame["macd_histogram_12_26_9"].tolist() == pytest.approx([v.histogram for v in expected])


def test_build_macd_features_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_macd_features(_bars(), price_type="ASK")


def test_build_macd_features_rejects_fast_not_less_than_slow():
    with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
        build_macd_features(_bars(), fast_period=26, slow_period=12)
