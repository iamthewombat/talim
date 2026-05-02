from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from talim.features import build_bollinger_features
from talim.strategy.indicators import bollinger


def _bars() -> pd.DataFrame:
    rows = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(25):
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


def test_build_bollinger_features_uses_mid_close_and_existing_indicator():
    frame = build_bollinger_features(
        _bars(),
        period=20,
        num_std=2.0,
        price_type="MID",
        computed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert list(frame.columns) == [
        "instrument",
        "timeframe",
        "timestamp",
        "basis_price_type",
        "close_mid",
        "bb_middle_20_2std",
        "bb_upper_20_2std",
        "bb_lower_20_2std",
        "bb_width_20_2std",
        "bb_percent_b_20_2std",
        "source",
        "computed_at_utc",
    ]
    assert len(frame) == 25
    assert frame["basis_price_type"].unique().tolist() == ["MID"]
    closes = [100.0 + i for i in range(25)]
    expected = bollinger(closes, period=20, num_std=2.0)
    assert frame["bb_middle_20_2std"].tolist() == pytest.approx(
        [float("nan") if v is None else v.middle for v in expected], nan_ok=True
    )
    assert frame["bb_upper_20_2std"].iloc[19] == pytest.approx(expected[19].upper)
    assert frame["bb_lower_20_2std"].iloc[19] == pytest.approx(expected[19].lower)
    assert frame["bb_percent_b_20_2std"].iloc[19] == pytest.approx(
        (closes[19] - expected[19].lower) / (expected[19].upper - expected[19].lower)
    )


def test_build_bollinger_features_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_bollinger_features(_bars(), price_type="ASK")
