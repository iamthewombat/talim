"""Tests for the shared ATR volatility-regime gate (backtest + live paths)."""

import numpy as np
import pandas as pd
import pytest

from talim.models.bar import OHLCVBar
from talim.regime.atr_gate import (
    MIN_BARS,
    atr_regime_allows,
    atr_regime_mask,
    parse_regime_filters,
)


def _make_vol_step_df(n: int = 250, loud_bars: int = 30, quiet: float = 0.5, loud: float = 8.0, loud_at_end: bool = True) -> pd.DataFrame:
    """Flat closes with a volatility step (wide-range bars at one end)."""
    close = np.full(n, 5000.0)
    rng = np.full(n, quiet)
    if loud_at_end:
        rng[-loud_bars:] = loud
    else:
        rng[: n - loud_bars] = loud
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="1D"),
            "open": close,
            "high": close + rng,
            "low": close - rng,
            "close": close,
            "volume": np.full(n, 1000.0),
        }
    )


def _df_to_bars(df: pd.DataFrame) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            instrument="ES",
            timestamp=row.timestamp.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in df.itertuples(index=False)
    ]


class TestAtrRegimeMask:
    def test_warmup_bars_are_false(self):
        df = _make_vol_step_df()
        for filt in ("atr-high", "atr-low"):
            mask = atr_regime_mask(df, filt)
            assert not mask.iloc[: MIN_BARS - 1].any()

    def test_high_vol_tail_is_atr_high(self):
        df = _make_vol_step_df(loud_at_end=True)
        assert bool(atr_regime_mask(df, "atr-high").iloc[-1])
        assert not bool(atr_regime_mask(df, "atr-low").iloc[-1])

    def test_quiet_tail_after_loud_head_is_atr_low(self):
        df = _make_vol_step_df(loud_at_end=False)
        assert bool(atr_regime_mask(df, "atr-low").iloc[-1])
        assert not bool(atr_regime_mask(df, "atr-high").iloc[-1])

    def test_invalid_filter_raises(self):
        df = _make_vol_step_df(n=20)
        with pytest.raises(ValueError, match="unknown regime_filter"):
            atr_regime_mask(df, "atr-medium")


class TestAtrRegimeAllows:
    def test_fails_closed_below_min_bars(self):
        bars = _df_to_bars(_make_vol_step_df(n=MIN_BARS - 1))
        assert atr_regime_allows(bars, "atr-high") is False
        assert atr_regime_allows(bars, "atr-low") is False

    def test_live_path_matches_vectorised_mask(self):
        df = _make_vol_step_df()
        bars = _df_to_bars(df)
        for filt in ("atr-high", "atr-low"):
            mask = atr_regime_mask(df, filt)
            for i in (MIN_BARS, len(bars) - 40, len(bars) - 1):
                assert atr_regime_allows(bars[: i + 1], filt) == bool(mask.iloc[i])


class TestParseRegimeFilters:
    def test_parses_multiple_entries(self):
        parsed = parse_regime_filters(
            " momentum-US500 : atr-high , rsi2-reversion:ATR-LOW "
        )
        assert parsed == {
            "momentum-US500": "atr-high",
            "rsi2-reversion": "atr-low",
        }

    def test_empty_or_none_gives_empty_dict(self):
        assert parse_regime_filters(None) == {}
        assert parse_regime_filters("") == {}
        assert parse_regime_filters(" , ") == {}

    def test_missing_colon_raises(self):
        with pytest.raises(ValueError, match="expected strategy:filter"):
            parse_regime_filters("momentum-US500")

    def test_invalid_filter_name_raises(self):
        with pytest.raises(ValueError, match="invalid regime filter"):
            parse_regime_filters("momentum-US500:atr-mid")
