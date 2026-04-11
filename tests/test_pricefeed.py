"""Tests for price feed connectors."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.connectors.pricefeed.normaliser import normalise_binance_kline
from talim.models.bar import OHLCVBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_df(n: int = 200) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    close = 5000.0 + np.cumsum(rng.randn(n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
        "open": close - rng.uniform(0, 2, n),
        "high": close + rng.uniform(0, 5, n),
        "low": close - rng.uniform(0, 5, n),
        "close": close,
        "volume": rng.uniform(5000, 15000, n),
    })


# ---------------------------------------------------------------------------
# MockPriceFeed tests
# ---------------------------------------------------------------------------

class TestMockPriceFeed:
    def test_replay_from_dataframe(self):
        df = _make_ohlcv_df(200)
        feed = MockPriceFeed(source=df, instrument="ES")
        feed.connect()
        bars = feed.replay()
        assert len(bars) == 200
        assert all(isinstance(b, OHLCVBar) for b in bars)

    def test_replay_invokes_callback(self):
        df = _make_ohlcv_df(50)
        feed = MockPriceFeed(source=df, instrument="ES")

        received: list[OHLCVBar] = []
        feed.on_bar(received.append)

        feed.replay()
        assert len(received) == 50
        assert received[0].instrument == "ES"

    def test_bar_fields_valid(self):
        df = _make_ohlcv_df(10)
        feed = MockPriceFeed(source=df, instrument="ES", timeframe="5m")
        bars = feed.replay()
        for bar in bars:
            assert bar.instrument == "ES"
            assert bar.timeframe == "5m"
            assert bar.high >= bar.low
            assert bar.volume > 0
            assert isinstance(bar.timestamp, datetime)

    def test_replay_without_load_raises(self):
        feed = MockPriceFeed(instrument="ES")
        with pytest.raises(RuntimeError):
            feed.replay()

    def test_load_parquet(self):
        df = _make_ohlcv_df(30)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.parquet"
            df.to_parquet(path)
            feed = MockPriceFeed(source=path, instrument="ES")
            bars = feed.replay()
            assert len(bars) == 30

    def test_load_csv(self):
        df = _make_ohlcv_df(30)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            df.to_csv(path, index=False)
            feed = MockPriceFeed(source=path, instrument="ES")
            bars = feed.replay()
            assert len(bars) == 30

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            MockPriceFeed(source="/nonexistent/file.parquet")

    def test_subscribe_tracking(self):
        feed = MockPriceFeed(source=_make_ohlcv_df(10), instrument="ES")
        feed.subscribe("ES")
        feed.subscribe("NQ")
        assert feed.subscriptions == {"ES", "NQ"}

    def test_connect_disconnect(self):
        feed = MockPriceFeed(source=_make_ohlcv_df(10), instrument="ES")
        assert not feed.is_connected
        feed.connect()
        assert feed.is_connected
        feed.disconnect()
        assert not feed.is_connected


# ---------------------------------------------------------------------------
# Normaliser tests
# ---------------------------------------------------------------------------

class TestNormaliser:
    def test_binance_kline_list_format(self):
        # REST format: [open_time, open, high, low, close, volume, close_time, ...]
        kline = [
            1700000000000, "5400.0", "5410.5", "5395.25", "5405.0", "12345.67",
            1700000299999, "66789000.0", 1200, "6500.0", "33000.0", "0",
        ]
        bar = normalise_binance_kline(kline, instrument="BTC/USDT", timeframe="5m")
        assert bar.instrument == "BTC/USDT"
        assert bar.open == 5400.0
        assert bar.high == 5410.5
        assert bar.low == 5395.25
        assert bar.close == 5405.0
        assert bar.volume == 12345.67
        assert bar.timeframe == "5m"

    def test_binance_kline_dict_format(self):
        kline = {
            "k": {
                "t": 1700000000000,
                "o": "5400.0",
                "h": "5410.5",
                "l": "5395.25",
                "c": "5405.0",
                "v": "12345.67",
            }
        }
        bar = normalise_binance_kline(kline, instrument="ETH/USDT", timeframe="1m")
        assert bar.instrument == "ETH/USDT"
        assert bar.close == 5405.0
        assert bar.timeframe == "1m"

    def test_binance_kline_flat_dict(self):
        k = {
            "t": 1700000000000,
            "o": "100", "h": "105", "l": "99", "c": "102", "v": "1000",
        }
        bar = normalise_binance_kline(k, instrument="X", timeframe="1h")
        assert bar.open == 100.0
        assert bar.close == 102.0

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            normalise_binance_kline("not a kline", instrument="X")  # type: ignore[arg-type]

    def test_timestamp_is_utc(self):
        kline = [1700000000000, "1", "2", "0.5", "1.5", "10"]
        bar = normalise_binance_kline(kline, instrument="X")
        assert bar.timestamp.tzinfo is not None
