"""Broker-agnostic CFD conformance tests (WP-61).

These tests prove that the Phase 10 BaseExchange contract behaves the same way
from the strategy/risk layer's point of view regardless of which venue adapter
is plugged in. Each adapter supplies a `VenueFixture` that handles request
translation; the assertions themselves are venue-neutral.

Scope (per WP-61 regression checklist):
- canonical instrument resolution
- order placement semantics (market + limit)
- stop/limit working-order handling (cancel round trip)
- position canonicalisation (venue-native models → single `Position`)
- margin / balance shape
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx
import pytest

from talim.cfd import load_default_registry
from talim.connectors.exchange.base import BaseExchange, OrderStatus
from talim.connectors.exchange.forexcom_discovery import ForexcomCredentials
from talim.connectors.exchange.forexcom_exchange import ForexcomExchange
from talim.connectors.exchange.ig_discovery import IgCredentials
from talim.connectors.exchange.ig_exchange import IgExchange


HandlerFn = Callable[[httpx.Request], httpx.Response]


@dataclass(frozen=True)
class VenueFixture:
    name: str
    build: Callable[[HandlerFn], BaseExchange]
    base_url: str
    handler: Callable[[dict], HandlerFn]
    # Expected canonical outputs — all venues must produce the same shape.
    expected_canonical_id: str = "AU200.cash"
    expected_currency: str = "AUD"


# --- IG fixture --------------------------------------------------------------


def _ig_handler(scenario: dict) -> HandlerFn:
    placed_limit = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/gateway/deal/positions/otc" and request.method == "POST":
            return httpx.Response(200, json={"dealReference": "ref-market"})
        if path == "/gateway/deal/confirms/ref-market":
            return httpx.Response(
                200,
                json={
                    "dealReference": "ref-market",
                    "dealStatus": "ACCEPTED",
                    "level": scenario["market_fill_price"],
                    "affectedDeals": [{"dealId": "deal-1", "status": "OPENED"}],
                },
            )
        if path == "/gateway/deal/working-orders/otc" and request.method == "POST":
            placed_limit["value"] = True
            return httpx.Response(200, json={"dealReference": "ref-limit"})
        if path == "/gateway/deal/confirms/ref-limit":
            return httpx.Response(
                200,
                json={
                    "dealReference": "ref-limit",
                    "dealStatus": "ACCEPTED",
                    "affectedDeals": [{"dealId": "deal-2", "status": "OPEN"}],
                },
            )
        if path == "/gateway/deal/working-orders/otc/deal-2" and request.method == "DELETE":
            return httpx.Response(200, json={"dealReference": "ref-cancel"})
        if path == "/gateway/deal/working-orders" and placed_limit["value"]:
            return httpx.Response(
                200,
                json={
                    "workingOrders": [
                        {
                            "marketData": {"epic": "IX.D.ASX.IFT.IP"},
                            "workingOrderData": {
                                "dealId": "deal-2",
                                "direction": "BUY",
                                "epic": "IX.D.ASX.IFT.IP",
                                "orderLevel": scenario["limit_price"],
                                "orderSize": scenario["limit_qty"],
                                "orderType": "LIMIT",
                            },
                        }
                    ]
                },
            )
        if path == "/gateway/deal/positions":
            return httpx.Response(
                200,
                json={
                    "positions": [
                        {
                            "market": {
                                "epic": "IX.D.ASX.IFT.IP",
                                "bid": scenario["bid"],
                                "offer": scenario["offer"],
                            },
                            "position": {
                                "dealId": "deal-1",
                                "direction": "BUY",
                                "size": scenario["market_qty"],
                                "level": scenario["market_fill_price"],
                                "contractSize": 1,
                                "createdDateUTC": "2026-04-18T10:15:00",
                            },
                        }
                    ]
                },
            )
        if path == "/gateway/deal/accounts":
            return httpx.Response(
                200,
                json={
                    "accounts": [
                        {
                            "accountId": "DEMO",
                            "currency": "AUD",
                            "preferred": True,
                            "status": "ENABLED",
                            "balance": {"balance": scenario["balance"], "available": scenario["balance"]},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected IG request: {request.method} {path}")

    return handler


def _ig_build(handler: HandlerFn) -> BaseExchange:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://demo-api.ig.com/gateway/deal")
    return IgExchange(
        credentials=IgCredentials(api_key="api-key", cst="cst", security_token="sec"),
        registry=load_default_registry(),
        client=client,
        confirm_delay_s=0.0,
    )


# --- FOREX.com fixture -------------------------------------------------------


def _forexcom_handler(scenario: dict) -> HandlerFn:
    cancelled = {"value": False}
    market_placed = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/TradingApi/session":
            return httpx.Response(200, json={"Session": "sess-1", "StatusCode": 1})
        if path == "/TradingApi/market/404709651/tickhistory":
            return httpx.Response(
                200,
                json={
                    "PriceTicks": [
                        {
                            "TickDate": "/Date(1776459600000)/",
                            "Price": scenario["market_fill_price"],
                            "Bid": scenario["bid"],
                            "Offer": scenario["offer"],
                            "AuditId": "audit-1",
                        }
                    ]
                },
            )
        if path == "/TradingApi/order/newtradeorder":
            market_placed["value"] = True
            return httpx.Response(
                200,
                json={"OrderId": 1001, "Status": 1, "Price": scenario["offer"]},
            )
        if path == "/TradingApi/order/newstoplimitorder":
            return httpx.Response(200, json={"OrderId": 1002, "Status": 1})
        if path == "/TradingApi/order/cancel":
            cancelled["value"] = True
            return httpx.Response(200, json={"Actions": [{"Status": 1, "OrderId": 1002}]})
        if path == "/TradingApi/order/openpositions":
            if market_placed["value"]:
                return httpx.Response(
                    200,
                    json={
                        "OpenPositions": [
                            {
                                "OrderId": 1001,
                                "MarketId": 404709651,
                                "Direction": "buy",
                                "Quantity": scenario["market_qty"],
                                "Price": scenario["market_fill_price"],
                                "CurrentPrice": scenario["bid"],
                                "LastChangedDateTimeUtc": "/Date(1776459600000)/",
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"OpenPositions": []})
        if path == "/TradingApi/margin/clientaccountmargin":
            return httpx.Response(
                200,
                json={
                    "Cash": scenario["balance"],
                    "TradableFunds": scenario["balance"],
                    "CurrencyIsoCode": "AUD",
                },
            )
        raise AssertionError(f"unexpected FOREX.com request: {request.method} {path}")

    return handler


def _forexcom_build(handler: HandlerFn) -> BaseExchange:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://ciapi.cityindex.com/TradingApi")
    return ForexcomExchange(
        credentials=ForexcomCredentials(login="user", password="pass", app_key="appkey"),
        trading_account_id=407617570,
        client_account_id=407561127,
        registry=load_default_registry(),
        client=client,
    )


VENUES = [
    VenueFixture(
        name="ig",
        build=_ig_build,
        base_url="https://demo-api.ig.com/gateway/deal",
        handler=_ig_handler,
    ),
    VenueFixture(
        name="forexcom",
        build=_forexcom_build,
        base_url="https://ciapi.cityindex.com/TradingApi",
        handler=_forexcom_handler,
    ),
]


DEFAULT_SCENARIO = {
    "market_qty": 1.0,
    "market_fill_price": 9000.0,
    "limit_qty": 2.0,
    "limit_price": 8950.0,
    "bid": 8999.0,
    "offer": 9001.0,
    "balance": 50_000.0,
}


@pytest.fixture(params=VENUES, ids=lambda f: f.name)
def venue(request) -> VenueFixture:
    return request.param


class TestCfdVenueConformance:
    def test_canonical_instrument_resolves_consistently(self, venue: VenueFixture):
        registry = load_default_registry()
        spec = registry.get(venue.expected_canonical_id)
        mapping = registry.resolve_mapping(venue.expected_canonical_id, venue.name)
        assert spec.quote_currency == venue.expected_currency
        assert mapping.is_resolved, f"{venue.name} mapping missing broker_symbol"

    def test_market_order_fills_and_returns_canonical_instrument(self, venue: VenueFixture):
        exchange = venue.build(venue.handler(DEFAULT_SCENARIO))
        order = exchange.place_order(venue.expected_canonical_id, "buy", 1.0, strategy="conformance")
        assert order.instrument == venue.expected_canonical_id
        assert order.side == "buy"
        assert order.status == OrderStatus.FILLED
        assert order.fill_price is not None

    def test_limit_order_round_trip_cancel(self, venue: VenueFixture):
        exchange = venue.build(venue.handler(DEFAULT_SCENARIO))
        order = exchange.place_order(
            venue.expected_canonical_id,
            "buy",
            DEFAULT_SCENARIO["limit_qty"],
            order_type="limit",
            limit_price=DEFAULT_SCENARIO["limit_price"],
        )
        assert order.status == OrderStatus.OPEN
        assert order.limit_price == DEFAULT_SCENARIO["limit_price"]

        cancelled = exchange.cancel_order(order.order_id)
        assert cancelled is True
        cached = exchange.get_order(order.order_id)
        assert cached is not None
        assert cached.status == OrderStatus.CANCELLED

    def test_positions_return_canonical_instrument_and_side(self, venue: VenueFixture):
        exchange = venue.build(venue.handler(DEFAULT_SCENARIO))
        # Prime the venue state where applicable (FOREX.com needs a prior trade
        # to expose an open position; IG always returns the fixture list).
        exchange.place_order(venue.expected_canonical_id, "buy", 1.0, strategy="conformance")
        positions = exchange.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.instrument == venue.expected_canonical_id
        assert pos.side == "long"
        assert pos.qty > 0
        assert pos.entry_price > 0

    def test_balance_shape_is_currency_keyed_float_map(self, venue: VenueFixture):
        exchange = venue.build(venue.handler(DEFAULT_SCENARIO))
        balance = exchange.get_account_balance()
        assert isinstance(balance, dict)
        assert venue.expected_currency in balance
        assert balance[venue.expected_currency] == pytest.approx(DEFAULT_SCENARIO["balance"])
