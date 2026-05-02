"""Tests for the FOREX.com price feed (WP-60)."""

from __future__ import annotations

import httpx
import pytest

from talim.cfd import load_default_registry
from talim.connectors.exchange.forexcom_discovery import ForexcomCredentials
from talim.connectors.pricefeed.forexcom import ForexcomPriceFeed


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://ciapi.cityindex.com/TradingApi",
    )


def _creds() -> ForexcomCredentials:
    return ForexcomCredentials(login="user", password="pass", app_key="appkey")


def _bar(ms: int, *, open_: float, high: float, low: float, close: float, volume: float):
    return {
        "BarDate": f"/Date({ms})/",
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }


class TestForexcomPriceFeed:
    def test_prime_history_emits_sorted_bars_once(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/market/404709651/barhistory":
                assert request.url.params["interval"] == "MINUTE"
                assert request.url.params["span"] == "5"
                return httpx.Response(
                    200,
                    json={
                        "PriceBars": [
                            _bar(1776458400000, open_=1.0, high=1.5, low=0.9, close=1.2, volume=5),
                            _bar(1776458700000, open_=1.2, high=1.4, low=1.1, close=1.3, volume=7),
                            _bar(1776459000000, open_=1.3, high=1.6, low=1.25, close=1.55, volume=9),
                        ],
                        "PartialPriceBar": _bar(
                            1776459300000, open_=1.55, high=1.6, low=1.5, close=1.58, volume=2
                        ),
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        feed = ForexcomPriceFeed(
            credentials=_creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_client(handler),
        )
        emitted: list = []
        feed.on_bar(lambda bar: emitted.append(bar))

        bars = feed.prime_history("AU200.cash", min_bars=50)
        assert len(bars) == 3
        assert emitted == bars
        # Partial bar is ignored — only completed bars are emitted.
        assert all(bar.timeframe == "5m" for bar in bars)
        assert [bar.close for bar in bars] == [1.2, 1.3, 1.55]
        # Second call with no newer data emits nothing.
        assert feed.poll_once("AU200.cash") is None

    def test_poll_once_emits_only_newest_bar(self):
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/market/404709651/barhistory":
                calls["count"] += 1
                return httpx.Response(
                    200,
                    json={
                        "PriceBars": [
                            _bar(1776458400000, open_=1.0, high=1.5, low=0.9, close=1.2, volume=5),
                            _bar(1776458700000, open_=1.2, high=1.4, low=1.1, close=1.3, volume=7),
                        ]
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        feed = ForexcomPriceFeed(
            credentials=_creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_client(handler),
        )
        emitted: list = []
        feed.on_bar(lambda bar: emitted.append(bar))

        bar = feed.poll_once("AU200.cash")
        assert bar is not None
        assert bar.close == pytest.approx(1.3)
        assert len(emitted) == 1
        # A second poll with the same latest bar returns None.
        assert feed.poll_once("AU200.cash") is None
        assert len(emitted) == 1
        assert calls["count"] == 2

    def test_fetch_bars_before_uses_paged_history_endpoint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/market/404709651/barhistorybefore":
                assert request.url.params["interval"] == "MINUTE"
                assert request.url.params["span"] == "5"
                assert request.url.params["toTimestampUTC"] == "1776459000"
                assert request.url.params["maxResults"] == "4000"
                assert request.url.params["priceType"] == "BID"
                return httpx.Response(
                    200,
                    json={
                        "PriceBars": [
                            _bar(1776458400000, open_=1.0, high=1.5, low=0.9, close=1.2, volume=5),
                            _bar(1776458700000, open_=1.2, high=1.4, low=1.1, close=1.3, volume=7),
                        ]
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        feed = ForexcomPriceFeed(
            credentials=_creds(),
            timeframe="5m",
            registry=load_default_registry(),
            client=_mock_client(handler),
        )

        bars = feed.fetch_bars_before(
            "AU200.cash",
            to_timestamp_utc=1776459000,
            count=5000,
            price_type="bid",
        )
        assert [bar.close for bar in bars] == [1.2, 1.3]

    def test_unsupported_timeframe_raises(self):
        with pytest.raises(ValueError):
            ForexcomPriceFeed(
                credentials=_creds(),
                timeframe="7m",
                registry=load_default_registry(),
                client=_mock_client(lambda r: httpx.Response(404)),
            )
