"""Tests for the FOREX.com exchange adapter (WP-60)."""

from __future__ import annotations

import json

import httpx
import pytest

from talim.cfd import load_default_registry
from talim.connectors.exchange.base import OrderStatus
from talim.connectors.exchange.forexcom_discovery import ForexcomCredentials
from talim.connectors.exchange.forexcom_exchange import (
    ForexcomExchange,
    ForexcomExchangeError,
)
from talim.models.position import Position


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://ciapi.cityindex.com/TradingApi",
    )


def _creds() -> ForexcomCredentials:
    return ForexcomCredentials(login="user", password="pass", app_key="appkey")


def _build_exchange(handler) -> ForexcomExchange:
    return ForexcomExchange(
        credentials=_creds(),
        trading_account_id=407617570,
        client_account_id=407561127,
        registry=load_default_registry(),
        client=_mock_client(handler),
    )


class TestForexcomExchange:
    def test_place_market_order_fetches_quote_and_fills(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/market/404709651/tickhistory":
                return httpx.Response(
                    200,
                    json={
                        "PriceTicks": [
                            {
                                "TickDate": "/Date(1776459600132)/",
                                "Price": 9031.7,
                                "Bid": 9031.2,
                                "Offer": 9032.2,
                                "AuditId": "audit-42",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/newtradeorder":
                body = request.content
                assert b'"MarketId":404709651' in body
                assert b'"Direction":"buy"' in body
                assert b'"AuditId":"audit-42"' in body
                assert b'"BidPrice":9031.2' in body
                assert b'"OfferPrice":9032.2' in body
                assert b'"IfDone"' in body
                assert b'"TriggerPrice":8950.0' in body
                assert b'"TriggerPrice":9100.0' in body
                return httpx.Response(
                    200,
                    json={"OrderId": 12345, "Status": 1, "Price": 9032.2},
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        order = exchange.place_order(
            "AU200.cash",
            "buy",
            1.0,
            strategy="momentum-AU200",
            stop_price=8950.0,
            target_price=9100.0,
        )

        assert order.order_id == "12345"
        assert order.instrument == "AU200.cash"
        assert order.status == OrderStatus.FILLED
        assert order.fill_price == 9032.2
        assert order.stop_price == 8950.0
        assert order.target_price == 9100.0

    def test_place_limit_order_returns_open_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/newstoplimitorder":
                body = request.content
                assert b'"TriggerPrice":9000.0' in body
                assert b'"Applicability":"GTC"' in body
                return httpx.Response(200, json={"OrderId": 99, "Status": 1})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        order = exchange.place_order(
            "AU200.cash", "buy", 2.0, order_type="limit", limit_price=9000.0
        )
        assert order.order_id == "99"
        assert order.status == OrderStatus.OPEN
        assert order.limit_price == 9000.0

    def test_cancel_order_marks_cached_order_cancelled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/newstoplimitorder":
                return httpx.Response(200, json={"OrderId": 99, "Status": 1})
            if request.url.path == "/TradingApi/order/cancel":
                body = request.content
                assert b'"OrderId":99' in body
                return httpx.Response(200, json={"Actions": [{"Status": 1, "OrderId": 99}]})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        order = exchange.place_order(
            "AU200.cash", "sell", 1.0, order_type="limit", limit_price=9100.0
        )
        assert exchange.cancel_order(order.order_id) is True
        cached = exchange.get_order(order.order_id)
        assert cached is not None
        assert cached.status == OrderStatus.CANCELLED

    def test_get_positions_aggregates_fifo_stack_into_logical_position(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/openpositions":
                assert request.url.params["TradingAccountId"] == "407617570"
                return httpx.Response(
                    200,
                    json={
                        "OpenPositions": [
                            {
                                "OrderId": 1001,
                                "MarketId": 404709651,
                                "Direction": "buy",
                                "Quantity": 1.0,
                                "Price": 9000.0,
                                "CurrentPrice": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459600000)/",
                            },
                            {
                                "OrderId": 1002,
                                "MarketId": 404709651,
                                "Direction": "buy",
                                "Quantity": 3.0,
                                "Price": 9100.0,
                                "CurrentPrice": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459700000)/",
                            },
                        ]
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        positions = exchange.get_positions()

        assert len(positions) == 1
        pos = positions[0]
        assert pos.instrument == "AU200.cash"
        assert pos.side == "long"
        assert pos.qty == pytest.approx(4.0)
        # VWAP = (1*9000 + 3*9100) / 4 = 9075
        assert pos.entry_price == pytest.approx(9075.0)
        # open_pnl = (9050 - 9075) * 4 = -100
        assert pos.open_pnl == pytest.approx(-100.0)
        # first lot's OrderId surfaces as the logical position id
        assert pos.position_id == "1001"

    def test_close_position_closes_fifo_lots(self):
        closed: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/openpositions":
                return httpx.Response(
                    200,
                    json={
                        "OpenPositions": [
                            {
                                "OrderId": 1001,
                                "MarketId": 404709651,
                                "Direction": "buy",
                                "Quantity": 1.0,
                                "Price": 9000.0,
                                "CurrentPrice": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459600000)/",
                            },
                            {
                                "OrderId": 1002,
                                "MarketId": 404709651,
                                "Direction": "buy",
                                "Quantity": 3.0,
                                "Price": 9010.0,
                                "CurrentPrice": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459700000)/",
                            },
                        ]
                    },
                )
            if request.url.path == "/TradingApi/market/404709651/tickhistory":
                return httpx.Response(
                    200,
                    json={
                        "PriceTicks": [
                            {
                                "TickDate": "/Date(1776459600132)/",
                                "Price": 9050.0,
                                "Bid": 9049.5,
                                "Offer": 9050.5,
                                "AuditId": "audit-close",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/close":
                payload = json.loads(request.content)
                closed.append(payload)
                return httpx.Response(
                    200,
                    json={"Actions": [{"Status": 1, "OrderId": payload["OrderId"]}]},
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        order = exchange.close_position(
            Position(
                instrument="AU200.cash",
                side="long",
                qty=2.5,
                entry_price=9008.0,
                stop=8950.0,
                target=9100.0,
                strategy="momentum-AU200",
                position_id="1001",
            )
        )

        assert order.status == OrderStatus.FILLED
        assert order.side == "sell"
        assert order.qty == 2.5
        assert [payload["OrderId"] for payload in closed] == [1001, 1002]
        assert [payload["MarketId"] for payload in closed] == [404709651, 404709651]
        assert [payload["Quantity"] for payload in closed] == [1.0, 1.5]
        assert all(payload["AuditId"] == "audit-close" for payload in closed)

    def test_get_account_balance_returns_currency_keyed_tradable_funds(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/margin/clientaccountmargin":
                assert request.url.params["ClientAccountId"] == "407561127"
                return httpx.Response(
                    200,
                    json={
                        "Cash": 50000.0,
                        "TradableFunds": 48000.0,
                        "CurrencyIsoCode": "AUD",
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        balance = exchange.get_account_balance()
        assert balance == {"AUD": 48000.0}

    def test_close_position_falls_back_to_opposite_market_order_when_close_route_missing(self):
        new_orders: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/openpositions":
                return httpx.Response(
                    200,
                    json={
                        "OpenPositions": [
                            {
                                "OrderId": 1001,
                                "MarketId": 404709651,
                                "Direction": "sell",
                                "Quantity": 1.0,
                                "Price": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459600000)/",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/market/404709651/tickhistory":
                return httpx.Response(
                    200,
                    json={
                        "PriceTicks": [
                            {
                                "TickDate": "/Date(1776459600132)/",
                                "Price": 9048.0,
                                "Bid": 9047.5,
                                "Offer": 9048.5,
                                "AuditId": "audit-fallback",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/close":
                return httpx.Response(405, text="")
            if request.url.path == "/TradingApi/useraccount/ClientAndTradingAccount":
                return httpx.Response(
                    200,
                    json={
                        "TradingAccounts": [
                            {"TradingAccountId": 407617570, "PositionMethodId": 1}
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/newtradeorder":
                payload = json.loads(request.content)
                new_orders.append(payload)
                return httpx.Response(200, json={"OrderId": 2002, "Status": 1})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        order = exchange.close_position(
            Position(
                instrument="AU200.cash",
                side="short",
                qty=1.0,
                entry_price=9050.0,
                stop=9100.0,
                target=9000.0,
                strategy="momentum-AU200",
                position_id="1001",
            )
        )

        assert order.status == OrderStatus.FILLED
        assert order.side == "buy"
        assert order.qty == 1.0
        assert new_orders[0]["Direction"] == "buy"
        assert new_orders[0]["Quantity"] == 1.0
        assert new_orders[0]["AuditId"] == "audit-fallback"

    def test_close_position_fallback_refused_on_non_fifo_account(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
            if request.url.path == "/TradingApi/order/openpositions":
                return httpx.Response(
                    200,
                    json={
                        "OpenPositions": [
                            {
                                "OrderId": 1001,
                                "MarketId": 404709651,
                                "Direction": "sell",
                                "Quantity": 1.0,
                                "Price": 9050.0,
                                "LastChangedDateTimeUtc": "/Date(1776459600000)/",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/market/404709651/tickhistory":
                return httpx.Response(
                    200,
                    json={
                        "PriceTicks": [
                            {
                                "TickDate": "/Date(1776459600132)/",
                                "Price": 9048.0,
                                "Bid": 9047.5,
                                "Offer": 9048.5,
                                "AuditId": "audit-fallback",
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/close":
                return httpx.Response(404, text="")
            if request.url.path == "/TradingApi/useraccount/ClientAndTradingAccount":
                return httpx.Response(
                    200,
                    json={
                        "TradingAccounts": [
                            {"TradingAccountId": 407617570, "PositionMethodId": 3}
                        ]
                    },
                )
            if request.url.path == "/TradingApi/order/newtradeorder":
                raise AssertionError("opposite market order must not be placed on non-FIFO accounts")
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = _build_exchange(handler)
        with pytest.raises(ForexcomExchangeError, match="not FIFO"):
            exchange.close_position(
                Position(
                    instrument="AU200.cash",
                    side="short",
                    qty=1.0,
                    entry_price=9050.0,
                    stop=9100.0,
                    target=9000.0,
                    strategy="momentum-AU200",
                    position_id="1001",
                )
            )
