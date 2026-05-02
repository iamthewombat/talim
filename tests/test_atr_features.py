from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from talim.features import build_atr_features
from talim.strategy.indicators import atr_wilder


def _bars() -> pd.DataFrame:
    rows = []
    for i in range(20):
        ts = f"2026-01-01T{i:02d}:00:00+00:00"
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "high": 110.0 + i,
                "low": 100.0 + i,
                "close": 105.0 + i,
                "price_type": "MID",
                "source": "forexcom",
            }
        )
        rows.append(
            {
                "instrument": "AU200.cash",
                "timeframe": "1h",
                "timestamp": ts,
                "high": 109.0 + i,
                "low": 99.0 + i,
                "close": 104.0 + i,
                "price_type": "BID",
                "source": "forexcom",
            }
        )
    return pd.DataFrame(rows)


def test_build_atr_features_uses_mid_ohlc_and_wilder_values():
    frame = build_atr_features(
        _bars(),
        period=14,
        price_type="MID",
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert list(frame.columns) == [
        "instrument",
        "timeframe",
        "timestamp",
        "basis_price_type",
        "atr_14",
        "source",
        "computed_at_utc",
    ]
    assert len(frame) == 20
    assert frame["basis_price_type"].unique().tolist() == ["MID"]
    assert frame["atr_14"].tolist() == pytest.approx(
        atr_wilder(
            [110.0 + i for i in range(20)],
            [100.0 + i for i in range(20)],
            [105.0 + i for i in range(20)],
            14,
        )
    )
    assert frame["atr_14"].iloc[0] == pytest.approx(10.0)


def test_build_atr_features_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_atr_features(_bars(), price_type="ASK")


def test_build_atr_features_accepts_bars_without_price_type():
    bars = _bars().query("price_type == 'MID'").drop(columns=["price_type"])

    frame = build_atr_features(bars, period=14, price_type="MID")

    assert frame["basis_price_type"].unique().tolist() == ["UNSPECIFIED"]
    assert len(frame) == 20
    assert frame["atr_14"].iloc[0] == pytest.approx(10.0)
