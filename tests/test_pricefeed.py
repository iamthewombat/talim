"""Tests for price feed connectors."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from talim.cfd import load_default_registry
from talim.connectors.exchange.ig_discovery import IgCredentials
from talim.connectors.pricefeed.factory import PriceFeedConfigError, create_pricefeed
from talim.connectors.pricefeed.ig import IgPriceFeed
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.connectors.pricefeed.normaliser import (
    PriceSnapshot,
    SnapshotBarBuilder,
    normalise_binance_kline,
    normalise_ig_price_bar,
    normalise_ig_snapshot,
)
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


def _mock_http_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://demo-api.ig.com/gateway/deal",
    )


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

    def test_ig_price_bar_midpoint_normaliser(self):
        payload = {
            "snapshotTimeUTC": "2026-04-13T09:30:00",
            "openPrice": {"bid": 100.0, "ask": 102.0, "lastTraded": None},
            "highPrice": {"bid": 104.0, "ask": 106.0, "lastTraded": None},
            "lowPrice": {"bid": 99.0, "ask": 101.0, "lastTraded": None},
            "closePrice": {"bid": 103.0, "ask": 105.0, "lastTraded": None},
            "lastTradedVolume": 12,
        }
        bar = normalise_ig_price_bar(payload, instrument="AU200.cash", timeframe="5m")
        assert bar.open == 101.0
        assert bar.high == 105.0
        assert bar.low == 100.0
        assert bar.close == 104.0
        assert bar.volume == 12.0

    def test_ig_market_snapshot_normaliser(self):
        payload = {"snapshot": {"bid": 100.0, "offer": 102.0}}
        snapshot = normalise_ig_snapshot(
            payload,
            instrument="AU200.cash",
            timestamp=datetime(2026, 4, 13, 9, 30, tzinfo=timezone.utc),
        )
        assert snapshot.instrument == "AU200.cash"
        assert snapshot.mid == 101.0


class TestSnapshotBarBuilder:
    def test_builder_rolls_snapshots_into_bars(self):
        builder = SnapshotBarBuilder(timeframe="5m")
        first = PriceSnapshot(
            instrument="AU200.cash",
            timestamp=datetime(2026, 4, 13, 9, 30, tzinfo=timezone.utc),
            bid=100.0,
            ask=102.0,
            volume=1.0,
        )
        second = PriceSnapshot(
            instrument="AU200.cash",
            timestamp=datetime(2026, 4, 13, 9, 34, tzinfo=timezone.utc),
            bid=103.0,
            ask=105.0,
            volume=2.0,
        )
        third = PriceSnapshot(
            instrument="AU200.cash",
            timestamp=datetime(2026, 4, 13, 9, 35, tzinfo=timezone.utc),
            bid=101.0,
            ask=103.0,
            volume=3.0,
        )
        assert builder.ingest(first) is None
        assert builder.ingest(second) is None
        completed = builder.ingest(third)
        assert completed is not None
        assert completed.timestamp == datetime(2026, 4, 13, 9, 30, tzinfo=timezone.utc)
        assert completed.open == 101.0
        assert completed.high == 104.0
        assert completed.low == 101.0
        assert completed.close == 104.0
        assert completed.volume == 3.0


class TestIgPriceFeed:
    @staticmethod
    def _creds() -> IgCredentials:
        return IgCredentials(api_key="api-key", cst="cst", security_token="sec")

    def test_fetch_bars_and_poll_once(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/prices/IX.D.ASX.IFT.IP":
                assert request.url.params["resolution"] == "MINUTE_5"
                max_size = int(request.url.params["max"])
                prices = [
                    {
                        "snapshotTimeUTC": "2026-04-13T09:30:00",
                        "openPrice": {"bid": 100.0, "ask": 102.0, "lastTraded": None},
                        "highPrice": {"bid": 104.0, "ask": 106.0, "lastTraded": None},
                        "lowPrice": {"bid": 99.0, "ask": 101.0, "lastTraded": None},
                        "closePrice": {"bid": 103.0, "ask": 105.0, "lastTraded": None},
                        "lastTradedVolume": 10,
                    },
                    {
                        "snapshotTimeUTC": "2026-04-13T09:35:00",
                        "openPrice": {"bid": 106.0, "ask": 108.0, "lastTraded": None},
                        "highPrice": {"bid": 107.0, "ask": 109.0, "lastTraded": None},
                        "lowPrice": {"bid": 105.0, "ask": 107.0, "lastTraded": None},
                        "closePrice": {"bid": 106.5, "ask": 108.5, "lastTraded": None},
                        "lastTradedVolume": 8,
                    },
                ]
                return httpx.Response(200, json={"prices": prices[-max_size:]})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        feed = IgPriceFeed(
            self._creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_http_client(handler),
        )
        feed.subscribe("AU200.cash")
        received: list[OHLCVBar] = []
        feed.on_bar(received.append)

        bars = feed.fetch_bars("AU200.cash", page_size=2)
        assert len(bars) == 2
        assert bars[0].instrument == "AU200.cash"

        primed = feed.prime_history("AU200.cash", min_bars=2)
        assert len(primed) == 2
        assert len(received) == 2

        assert feed.poll_once("AU200.cash") is None  # newest bar already emitted

    def test_poll_snapshot_once_uses_builder(self):
        calls = {"markets": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/markets/IX.D.ASX.IFT.IP":
                calls["markets"] += 1
                if calls["markets"] == 1:
                    update = "09:30:00"
                    bid, offer = 100.0, 102.0
                else:
                    update = "09:35:00"
                    bid, offer = 104.0, 106.0
                return httpx.Response(200, json={"snapshot": {"bid": bid, "offer": offer, "updateTime": update}})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        feed = IgPriceFeed(
            self._creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_http_client(handler),
        )
        feed.subscribe("AU200.cash")

        assert feed.poll_snapshot_once("AU200.cash") is None
        bar = feed.poll_snapshot_once("AU200.cash")
        assert bar is not None
        assert bar.instrument == "AU200.cash"
        assert bar.timestamp.minute == 30

    def test_fetch_recent_bars_walks_latest_pages(self):
        def _bar_payload(ts: str, mid: float) -> dict:
            return {
                "snapshotTimeUTC": ts,
                "openPrice": {"bid": mid - 1.0, "ask": mid + 1.0, "lastTraded": None},
                "highPrice": {"bid": mid + 1.0, "ask": mid + 3.0, "lastTraded": None},
                "lowPrice": {"bid": mid - 2.0, "ask": mid, "lastTraded": None},
                "closePrice": {"bid": mid, "ask": mid + 2.0, "lastTraded": None},
                "lastTradedVolume": 5,
            }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path != "/gateway/deal/prices/IX.D.ASX.IFT.IP/MINUTE_5/5":
                raise AssertionError(f"unexpected request: {request.method} {request.url}")
            return httpx.Response(
                200,
                json={
                    "prices": [
                        _bar_payload("2026-04-01T09:35:00", 101.0),
                        _bar_payload("2026-04-01T09:40:00", 102.0),
                        _bar_payload("2026-04-01T09:45:00", 103.0),
                        _bar_payload("2026-04-01T09:50:00", 104.0),
                        _bar_payload("2026-04-01T09:55:00", 105.0),
                    ]
                },
            )

        feed = IgPriceFeed(
            self._creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_http_client(handler),
        )
        bars = feed.fetch_recent_bars("AU200.cash", total_bars=5, page_size=2)
        assert len(bars) == 5
        assert bars[0].timestamp.minute == 35
        assert bars[-1].timestamp.minute == 55


class TestPriceFeedFactory:
    def test_invalid_pricefeed_raises(self):
        with pytest.raises(PriceFeedConfigError):
            create_pricefeed("nope")

    def test_factory_creates_ig_feed(self, monkeypatch):
        monkeypatch.setenv("IG_DEMO_API_KEY", "demo-api-key")
        monkeypatch.setenv("IG_DEMO_LOGIN", "demo-user")
        monkeypatch.setenv("IG_DEMO_PASSWORD", "demo-pass")
        feed = create_pricefeed("ig", timeframe="5m")
        assert isinstance(feed, IgPriceFeed)
        assert feed.credentials.environment == "demo"
