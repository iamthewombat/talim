"""Tests for the exchange factory and ccxt integration (WP-32)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from talim.connectors.exchange.base import BaseExchange, Order, OrderStatus
from talim.connectors.exchange.factory import (
    ExchangeConfigError,
    create_exchange,
)
from talim.connectors.exchange.ig_exchange import IgExchange
from talim.connectors.exchange.mock_exchange import MockExchange


# --- Factory mode selection ---


class TestCreateExchangeMock:
    def test_default_is_mock(self):
        ex = create_exchange()
        assert isinstance(ex, MockExchange)

    def test_explicit_mock(self):
        ex = create_exchange(mode="mock")
        assert isinstance(ex, MockExchange)

    def test_mock_custom_balance(self):
        ex = create_exchange(mode="mock", starting_balance=50_000.0)
        assert ex.get_account_balance()["USD"] == 50_000.0

    def test_invalid_mode_raises(self):
        with pytest.raises(ExchangeConfigError, match="invalid"):
            create_exchange(mode="paper")

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
        ex = create_exchange()
        assert isinstance(ex, MockExchange)


class TestCreateExchangeTestnet:
    def test_missing_exchange_name_raises(self, monkeypatch):
        monkeypatch.delenv("TALIM_EXCHANGE_NAME", raising=False)
        with pytest.raises(ExchangeConfigError, match="TALIM_EXCHANGE_NAME"):
            create_exchange(mode="testnet")

    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.setenv("TALIM_EXCHANGE_NAME", "binance")
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        with pytest.raises(ExchangeConfigError, match="missing credentials"):
            create_exchange(mode="testnet", exchange_name="binance")

    def test_testnet_creates_sandbox_exchange(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "test-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")

        # Mock ccxt to avoid needing the real package
        mock_ccxt = MagicMock()
        mock_exchange_cls = MagicMock()
        mock_exchange_instance = MagicMock()
        mock_exchange_cls.return_value = mock_exchange_instance
        mock_ccxt.binance = mock_exchange_cls

        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            ex = create_exchange(mode="testnet", exchange_name="binance")

        assert ex is not None
        mock_exchange_instance.set_sandbox_mode.assert_called_once_with(True)

    def test_testnet_creates_ig_demo_exchange(self, monkeypatch):
        monkeypatch.setenv("IG_DEMO_API_KEY", "demo-api-key")
        monkeypatch.setenv("IG_DEMO_LOGIN", "demo-user")
        monkeypatch.setenv("IG_DEMO_PASSWORD", "demo-pass")

        ex = create_exchange(mode="testnet", exchange_name="ig")

        assert isinstance(ex, IgExchange)
        assert ex.credentials.environment == "demo"


class TestCreateExchangeLive:
    def test_live_creates_production_exchange(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "live-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "live-secret")

        mock_ccxt = MagicMock()
        mock_exchange_cls = MagicMock()
        mock_exchange_instance = MagicMock()
        mock_exchange_cls.return_value = mock_exchange_instance
        mock_ccxt.binance = mock_exchange_cls

        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            ex = create_exchange(mode="live", exchange_name="binance")

        assert ex is not None
        # Live mode should NOT call set_sandbox_mode
        mock_exchange_instance.set_sandbox_mode.assert_not_called()

    def test_live_creates_ig_live_exchange(self, monkeypatch):
        monkeypatch.setenv("IG_API_KEY", "live-api-key")
        monkeypatch.setenv("IG_IDENTIFIER", "live-user")
        monkeypatch.setenv("IG_PASSWORD", "live-pass")

        ex = create_exchange(mode="live", exchange_name="ig")

        assert isinstance(ex, IgExchange)
        assert ex.credentials.environment == "live"


# --- CcxtExchange integration (mocked ccxt responses) ---


class TestCcxtExchangeMocked:
    """Test CcxtExchange methods with a mocked ccxt client."""

    @pytest.fixture()
    def exchange(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")

        mock_ccxt = MagicMock()
        mock_client = MagicMock()
        mock_ccxt.binance.return_value = mock_client

        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            ex = create_exchange(mode="testnet", exchange_name="binance")
        # Expose the mock client for assertions
        ex._mock_client = mock_client
        return ex

    def test_place_order_market(self, exchange):
        exchange._mock_client.create_order.return_value = {
            "id": "ord-123",
            "status": "closed",
            "average": 5005.0,
        }
        order = exchange.place_order("ES", "buy", 1.0, strategy="momentum-US500")
        assert order.order_id == "ord-123"
        assert order.status == OrderStatus.FILLED
        assert order.fill_price == 5005.0

    def test_get_positions_parses_response(self, exchange):
        exchange._mock_client.fetch_positions.return_value = [
            {
                "symbol": "BTC/USDT",
                "side": "long",
                "contracts": 0.5,
                "entryPrice": 60000.0,
                "unrealizedPnl": 150.0,
            },
            {
                "symbol": "ETH/USDT",
                "side": "short",
                "contracts": 0,  # zero qty — should be filtered out
                "entryPrice": 3000.0,
                "unrealizedPnl": 0.0,
            },
        ]
        positions = exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].instrument == "BTC/USDT"
        assert positions[0].side == "long"
        assert positions[0].qty == 0.5
        assert positions[0].open_pnl == 150.0

    def test_get_account_balance(self, exchange):
        exchange._mock_client.fetch_balance.return_value = {
            "total": {"USDT": 50000.0, "BTC": 0.5, "ETH": 0},
        }
        balance = exchange.get_account_balance()
        assert balance["USDT"] == 50000.0
        assert balance["BTC"] == 0.5
        assert "ETH" not in balance  # zero filtered

    def test_cancel_order_success(self, exchange):
        exchange._mock_client.cancel_order.return_value = {}
        assert exchange.cancel_order("ord-123") is True

    def test_cancel_order_failure(self, exchange):
        exchange._mock_client.cancel_order.side_effect = Exception("not found")
        assert exchange.cancel_order("ord-999") is False

    def test_get_order(self, exchange):
        exchange._mock_client.fetch_order.return_value = {
            "id": "ord-456",
            "symbol": "ES",
            "side": "sell",
            "amount": 2.0,
            "type": "market",
            "price": None,
            "average": 5010.0,
        }
        order = exchange.get_order("ord-456")
        assert order is not None
        assert order.order_id == "ord-456"
        assert order.side == "sell"
        assert order.qty == 2.0

    def test_get_order_not_found(self, exchange):
        exchange._mock_client.fetch_order.side_effect = Exception("not found")
        assert exchange.get_order("nope") is None
