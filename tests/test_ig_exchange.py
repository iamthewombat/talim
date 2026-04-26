"""Tests for the IG OTC exchange adapter."""

from __future__ import annotations

import httpx

import pytest

from talim.cfd import load_default_registry
from talim.connectors.exchange.base import OrderStatus
from talim.connectors.exchange.ig_discovery import IgCredentials
from talim.connectors.exchange.ig_exchange import IgExchange


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://demo-api.ig.com/gateway/deal",
    )


def _creds() -> IgCredentials:
    return IgCredentials(api_key="api-key", cst="cst", security_token="sec")


class TestIgExchange:
    def test_place_market_order_and_lookup_position(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/positions/otc":
                payload = request.content
                assert b'"orderType":"MARKET"' in payload
                assert b'"epic":"IX.D.ASX.IFT.IP"' in payload
                assert b'"stopLevel":8050.0' in payload
                assert b'"limitLevel":8200.0' in payload
                return httpx.Response(200, json={"dealReference": "ref-market"})
            if request.url.path == "/gateway/deal/confirms/ref-market":
                return httpx.Response(
                    200,
                    json={
                        "dealReference": "ref-market",
                        "dealStatus": "ACCEPTED",
                        "level": 8123.4,
                        "affectedDeals": [{"dealId": "deal-market-1", "status": "OPENED"}],
                    },
                )
            if request.url.path == "/gateway/deal/positions":
                return httpx.Response(
                    200,
                    json={
                        "positions": [
                            {
                                "market": {
                                    "epic": "IX.D.ASX.IFT.IP",
                                    "bid": 8125.0,
                                    "offer": 8126.0,
                                },
                                "position": {
                                    "dealId": "deal-market-1",
                                    "direction": "BUY",
                                    "size": 1.5,
                                    "level": 8123.4,
                                    "contractSize": 1,
                                    "createdDateUTC": "2026-04-12T10:15:00",
                                },
                            }
                        ]
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = IgExchange(
            credentials=_creds(),
            registry=load_default_registry(),
            client=_mock_client(handler),
            confirm_delay_s=0.0,
        )

        order = exchange.place_order(
            "AU200.cash",
            "buy",
            1.5,
            strategy="momentum-AU200",
            stop_price=8050.0,
            target_price=8200.0,
        )
        assert order.order_id == "deal-market-1"
        assert order.instrument == "AU200.cash"
        assert order.status == OrderStatus.FILLED
        assert order.fill_price == 8123.4
        assert order.stop_price == 8050.0
        assert order.target_price == 8200.0

        fetched = exchange.get_order("deal-market-1")
        assert fetched is not None
        assert fetched.status == OrderStatus.FILLED
        assert fetched.instrument == "AU200.cash"

        positions = exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].instrument == "AU200.cash"
        assert positions[0].side == "long"
        assert positions[0].position_id == "deal-market-1"
        assert positions[0].open_pnl == pytest.approx(2.4)

    def test_place_limit_order_cancel_and_lookup(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/working-orders/otc" and request.method == "POST":
                payload = request.content
                assert b'"type":"LIMIT"' in payload
                assert b'"level":8100.5' in payload
                return httpx.Response(200, json={"dealReference": "ref-limit"})
            if request.url.path == "/gateway/deal/confirms/ref-limit":
                return httpx.Response(
                    200,
                    json={
                        "dealReference": "ref-limit",
                        "dealStatus": "ACCEPTED",
                        "affectedDeals": [{"dealId": "deal-limit-1", "status": "OPEN"}],
                    },
                )
            if request.url.path == "/gateway/deal/working-orders":
                return httpx.Response(
                    200,
                    json={
                        "workingOrders": [
                            {
                                "marketData": {"epic": "IX.D.ASX.IFT.IP"},
                                "workingOrderData": {
                                    "dealId": "deal-limit-1",
                                    "direction": "BUY",
                                    "epic": "IX.D.ASX.IFT.IP",
                                    "orderLevel": 8100.5,
                                    "orderSize": 2.0,
                                    "orderType": "LIMIT",
                                },
                            }
                        ]
                    },
                )
            if request.url.path == "/gateway/deal/working-orders/otc/deal-limit-1" and request.method == "DELETE":
                return httpx.Response(200, json={"dealReference": "ref-limit-cancel"})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = IgExchange(
            credentials=_creds(),
            registry=load_default_registry(),
            client=_mock_client(handler),
            confirm_delay_s=0.0,
        )

        order = exchange.place_order("AU200.cash", "buy", 2.0, order_type="limit", limit_price=8100.5)
        assert order.order_id == "deal-limit-1"
        assert order.status == OrderStatus.OPEN
        assert order.limit_price == 8100.5

        fetched = exchange.get_order("deal-limit-1")
        assert fetched is not None
        assert fetched.status == OrderStatus.OPEN
        assert fetched.limit_price == 8100.5

        assert exchange.cancel_order("deal-limit-1") is True
        cancelled = exchange.get_order("deal-limit-1")
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED

    def test_get_account_balance_uses_preferred_account(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/accounts":
                return httpx.Response(
                    200,
                    json={
                        "accounts": [
                            {
                                "accountId": "ABC",
                                "currency": "AUD",
                                "preferred": True,
                                "status": "ENABLED",
                                "balance": {
                                    "available": 1000.0,
                                    "balance": 1500.0,
                                },
                            }
                        ]
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        exchange = IgExchange(
            credentials=_creds(),
            registry=load_default_registry(),
            client=_mock_client(handler),
            confirm_delay_s=0.0,
        )

        balance = exchange.get_account_balance()
        assert balance == {"AUD": 1500.0}
