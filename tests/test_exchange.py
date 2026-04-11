"""Tests for exchange connectors."""

import os

import pytest

from talim.connectors.exchange.base import Order, OrderStatus
from talim.connectors.exchange.credentials import load_credentials
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.models.position import Position


# ---------------------------------------------------------------------------
# MockExchange tests
# ---------------------------------------------------------------------------

class TestMockExchange:
    def test_place_market_order_fills_immediately(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        order = ex.place_order("ES", "buy", qty=2.0, strategy="momentum-ES")

        assert order.status == OrderStatus.FILLED
        assert order.fill_price == 5400.0
        assert order.fill_time is not None

    def test_fill_creates_position(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        ex.place_order("ES", "buy", qty=2.0, strategy="momentum-ES")

        positions = ex.get_positions()
        assert len(positions) == 1
        assert positions[0].instrument == "ES"
        assert positions[0].side == "long"
        assert positions[0].qty == 2.0
        assert positions[0].entry_price == 5400.0

    def test_short_position(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        ex.place_order("ES", "sell", qty=1.0)

        positions = ex.get_positions()
        assert len(positions) == 1
        assert positions[0].side == "short"

    def test_close_position_removes_it(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        ex.place_order("ES", "buy", qty=2.0)
        assert len(ex.get_positions()) == 1

        ex.place_order("ES", "sell", qty=2.0)
        assert len(ex.get_positions()) == 0

    def test_partial_close(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        ex.place_order("ES", "buy", qty=3.0)
        ex.place_order("ES", "sell", qty=1.0)

        positions = ex.get_positions()
        assert len(positions) == 1
        assert positions[0].qty == 2.0
        assert positions[0].side == "long"

    def test_cancel_limit_order(self):
        ex = MockExchange()
        order = ex.place_order(
            "ES", "buy", qty=1.0, order_type="limit", limit_price=5300.0
        )
        assert order.status == OrderStatus.OPEN

        cancelled = ex.cancel_order(order.order_id)
        assert cancelled is True
        assert ex.get_order(order.order_id).status == OrderStatus.CANCELLED

    def test_cannot_cancel_filled_order(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        order = ex.place_order("ES", "buy", qty=1.0)
        assert ex.cancel_order(order.order_id) is False

    def test_cancel_nonexistent_order(self):
        ex = MockExchange()
        assert ex.cancel_order("nonexistent-id") is False

    def test_get_order_by_id(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        order = ex.place_order("ES", "buy", qty=1.0)
        fetched = ex.get_order(order.order_id)
        assert fetched is not None
        assert fetched.order_id == order.order_id

    def test_account_balance(self):
        ex = MockExchange(starting_balance=100000.0)
        assert ex.get_account_balance()["USD"] == 100000.0

        ex.set_fill_price("ES", 5400.0)
        ex.place_order("ES", "buy", qty=2.0)
        # Balance reduced by cost
        assert ex.get_account_balance()["USD"] == 100000.0 - (2.0 * 5400.0)

    def test_invalid_side_raises(self):
        ex = MockExchange()
        with pytest.raises(ValueError):
            ex.place_order("ES", "invalid", qty=1.0)

    def test_invalid_qty_raises(self):
        ex = MockExchange()
        with pytest.raises(ValueError):
            ex.place_order("ES", "buy", qty=0)

    def test_multiple_instruments(self):
        ex = MockExchange()
        ex.set_fill_price("ES", 5400.0)
        ex.set_fill_price("NQ", 18000.0)

        ex.place_order("ES", "buy", qty=1.0)
        ex.place_order("NQ", "buy", qty=1.0)

        positions = ex.get_positions()
        assert len(positions) == 2
        instruments = {p.instrument for p in positions}
        assert instruments == {"ES", "NQ"}


# ---------------------------------------------------------------------------
# Credentials tests
# ---------------------------------------------------------------------------

class TestCredentials:
    def test_load_credentials_success(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "my-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "my-secret")

        creds = load_credentials("binance")
        assert creds.exchange == "binance"
        assert creds.api_key == "my-key"
        assert creds.api_secret == "my-secret"

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        with pytest.raises(KeyError):
            load_credentials("binance")

    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.setenv("BYBIT_API_KEY", "key-only")
        monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
        with pytest.raises(KeyError):
            load_credentials("bybit")

    def test_case_insensitive_exchange(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        creds = load_credentials("Binance")
        assert creds.api_key == "k"
