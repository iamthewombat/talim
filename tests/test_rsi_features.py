from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from talim.features import build_rsi_features
from talim.features.rsi import merge_feature_file
from talim.strategy.indicators import rsi_wilder


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


def test_build_rsi_features_uses_mid_close_and_wilder_values():
    frame = build_rsi_features(
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
        "close_mid",
        "rsi_14",
        "source",
        "computed_at_utc",
    ]
    assert len(frame) == 20
    assert frame["basis_price_type"].unique().tolist() == ["MID"]
    assert frame["close_mid"].tolist() == [100.0 + i for i in range(20)]
    assert frame["rsi_14"].tolist() == pytest.approx(
        [float("nan") if v is None else v for v in rsi_wilder([100.0 + i for i in range(20)], 14)],
        nan_ok=True,
    )
    assert frame["rsi_14"].iloc[14] == pytest.approx(100.0)


def test_build_rsi_features_rejects_missing_price_type():
    with pytest.raises(ValueError, match="no ASK bars"):
        build_rsi_features(_bars(), price_type="ASK")


def test_merge_feature_file_preserves_existing_columns(tmp_path):
    output = tmp_path / "features.parquet"
    existing = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00+00:00"],
            "ema_20": [123.0],
        }
    )
    existing.to_parquet(output, index=False)
    new = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00+00:00"],
            "rsi_14": [55.0],
        }
    )

    merged = merge_feature_file(new, output)

    assert merged.loc[0, "ema_20"] == pytest.approx(123.0)
    assert merged.loc[0, "rsi_14"] == pytest.approx(55.0)
