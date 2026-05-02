from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from talim.features import build_ema_features
from talim.strategy.indicators import ema


def _bars() -> pd.DataFrame:
    rows = []
    for i in range(20):
        ts = f"2026-01-01T{i:02d}:00:00+00:00"
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


def test_build_ema_features_uses_mid_close_and_existing_ema():
    frame = build_ema_features(
        _bars(),
        period=20,
        price_type="MID",
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert list(frame.columns) == [
        "instrument",
        "timeframe",
        "timestamp",
        "basis_price_type",
        "ema_20",
        "source",
        "computed_at_utc",
    ]
    assert len(frame) == 20
    assert frame["basis_price_type"].unique().tolist() == ["MID"]
    assert frame["ema_20"].tolist() == pytest.approx(ema([100.0 + i for i in range(20)], 20))
    assert frame["ema_20"].iloc[0] == pytest.approx(100.0)


def test_build_ema_features_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_ema_features(_bars(), price_type="ASK")
