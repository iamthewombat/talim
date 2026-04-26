"""Tests for the FOREX.com / StoneX discovery client used in WP-60."""

from __future__ import annotations

import httpx
import pytest

from talim.connectors.exchange.forexcom_discovery import (
    ForexcomCredentials,
    ForexcomDiscoveryClient,
    ForexcomDiscoveryError,
    ForexcomMarketDetails,
)


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://ciapi.cityindex.com/TradingApi",
    )


def _creds() -> ForexcomCredentials:
    return ForexcomCredentials(login="user", password="pass", app_key="appkey")


class TestForexcomCredentials:
    def test_from_env_reads_login_password_app_key(self, monkeypatch):
        monkeypatch.setenv("FOREXDOTCOM_LOGIN", "user")
        monkeypatch.setenv("FOREXDOTCOM_PASSWORD", "pass")
        monkeypatch.setenv("FOREXDOTCOM_APP_KEY", "appkey")
        creds = ForexcomCredentials.from_env()
        assert creds.login == "user"
        assert creds.password == "pass"
        assert creds.app_key == "appkey"
        assert creds.environment == "live"

    def test_from_env_fails_when_any_part_missing(self, monkeypatch):
        monkeypatch.setenv("FOREXDOTCOM_LOGIN", "user")
        monkeypatch.delenv("FOREXDOTCOM_PASSWORD", raising=False)
        monkeypatch.setenv("FOREXDOTCOM_APP_KEY", "appkey")
        with pytest.raises(ValueError):
            ForexcomCredentials.from_env()


class TestForexcomDiscoveryClient:
    def test_create_session_search_and_get_market(self):
        captured: dict[str, httpx.Request] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured[request.url.path] = request
            if request.url.path == "/TradingApi/session":
                return httpx.Response(
                    200,
                    json={"Session": "sess-guid-1", "StatusCode": 1},
                )
            if request.url.path == "/TradingApi/cfd/markets":
                assert request.url.params["MarketName"] == "Australia 200"
                assert request.headers["UserName"] == "user"
                assert request.headers["Session"] == "sess-guid-1"
                return httpx.Response(
                    200,
                    json={
                        "Markets": [
                            {
                                "MarketId": 404709651,
                                "Name": "Australia 200 CFD",
                                "Weighting": 100000,
                            }
                        ]
                    },
                )
            if request.url.path == "/TradingApi/market/404709651/information":
                return httpx.Response(
                    200,
                    json={
                        "MarketInformation": {
                            "MarketId": 404709651,
                            "Name": "Australia 200 CFD",
                            "MarketSettingsType": "CFD",
                            "MarketUnderlyingType": "Index",
                            "MarginFactor": 5,
                            "MarginFactorUnits": 26,
                            "IncrementSize": 0.1,
                            "WebMinSize": 0.1,
                            "PriceDecimalPlaces": 1,
                            "AllowGuaranteedOrders": True,
                            "ExpiryUtc": None,
                            "Market24H": True,
                        }
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = ForexcomDiscoveryClient(credentials=_creds(), client=_mock_client(handler))

        markets = client.search_markets("Australia 200")
        assert len(markets) == 1
        assert markets[0].market_id == "404709651"
        assert markets[0].name == "Australia 200 CFD"

        details = client.get_market("404709651", currency_iso_code="AUD")
        assert details.market_id == "404709651"
        assert details.margin_factor == 5.0
        assert details.margin_factor_units == 26
        assert details.increment_size == pytest.approx(0.1)
        assert details.price_decimal_places == 1
        assert details.market_24h is True
        assert details.expiry_utc_ms is None

        # session POST uses UNauthenticated headers
        session_req = captured["/TradingApi/session"]
        assert "UserName" not in session_req.headers

    def test_create_session_raises_when_status_code_not_accepted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/TradingApi/session":
                return httpx.Response(
                    200,
                    json={
                        "Session": None,
                        "StatusCode": 2,
                        "AdditionalInfo": "login failed",
                    },
                )
            raise AssertionError("unexpected request")

        client = ForexcomDiscoveryClient(credentials=_creds(), client=_mock_client(handler))
        with pytest.raises(ForexcomDiscoveryError):
            client.create_session()

    def test_build_registry_patch_converts_percentage_margin(self):
        details = ForexcomMarketDetails(
            market_id="404709651",
            name="Australia 200 CFD",
            market_settings_type="CFD",
            market_underlying_type="Index",
            currency_iso_code="AUD",
            margin_factor=5.0,
            margin_factor_units=26,
            increment_size=0.1,
            web_min_size=0.1,
            price_decimal_places=1,
            allow_guaranteed_orders=True,
            guaranteed_order_premium=1.0,
            guaranteed_order_min_distance=110.0,
            expiry_utc_ms=None,
            market_24h=True,
            raw={},
        )
        client = ForexcomDiscoveryClient(
            credentials=_creds(),
            client=_mock_client(lambda r: httpx.Response(404)),
        )
        patch = client.build_registry_patch(canonical_id="AU200.cash", details=details)
        assert patch["canonical_id"] == "AU200.cash"
        assert patch["asset_class"] == "index_cfd"
        assert patch["quote_currency"] == "AUD"
        assert patch["margin_rate"] == pytest.approx(0.05)
        assert patch["tick_size"] == pytest.approx(0.1)
        assert patch["venues"]["forexcom"]["market_id"] == "404709651"
