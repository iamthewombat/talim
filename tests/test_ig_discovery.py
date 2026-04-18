"""Tests for the IG discovery client used in WP-49."""

from __future__ import annotations

import httpx
import pytest

from talim.connectors.exchange.ig_discovery import (
    IgCredentials,
    IgDiscoveryClient,
    IgMarketDetails,
)


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        base_url="https://demo-api.ig.com/gateway/deal",
    )


class TestIgCredentials:
    def test_from_env_supports_password_login(self, monkeypatch):
        monkeypatch.setenv("IG_API_KEY", "api-key")
        monkeypatch.setenv("IG_IDENTIFIER", "user")
        monkeypatch.setenv("IG_PASSWORD", "pass")
        monkeypatch.setenv("IG_ENVIRONMENT", "demo")

        creds = IgCredentials.from_env()
        assert creds.api_key == "api-key"
        assert creds.identifier == "user"
        assert creds.environment == "demo"

    def test_from_env_supports_preissued_tokens(self, monkeypatch):
        monkeypatch.setenv("IG_API_KEY", "api-key")
        monkeypatch.setenv("IG_CST", "cst")
        monkeypatch.setenv("IG_SECURITY_TOKEN", "sec")
        monkeypatch.delenv("IG_IDENTIFIER", raising=False)
        monkeypatch.delenv("IG_PASSWORD", raising=False)

        creds = IgCredentials.from_env()
        assert creds.has_session_tokens is True

    def test_from_env_supports_demo_prefixed_names(self, monkeypatch):
        monkeypatch.delenv("IG_API_KEY", raising=False)
        monkeypatch.delenv("IG_IDENTIFIER", raising=False)
        monkeypatch.delenv("IG_PASSWORD", raising=False)
        monkeypatch.setenv("IG_DEMO_API_KEY", "demo-api-key")
        monkeypatch.setenv("IG_DEMO_LOGIN", "demo-user")
        monkeypatch.setenv("IG_DEMO_PASSWORD", "demo-pass")

        creds = IgCredentials.from_env()
        assert creds.api_key == "demo-api-key"
        assert creds.identifier == "demo-user"
        assert creds.password == "demo-pass"
        assert creds.environment == "demo"

    def test_from_env_prefers_demo_api_key_in_demo_environment(self, monkeypatch):
        monkeypatch.setenv("IG_API_KEY", "live-style-key")
        monkeypatch.setenv("IG_DEMO_API_KEY", "demo-key")
        monkeypatch.setenv("IG_DEMO_LOGIN", "demo-user")
        monkeypatch.setenv("IG_DEMO_PASSWORD", "demo-pass")
        monkeypatch.setenv("IG_ENVIRONMENT", "demo")

        creds = IgCredentials.from_env()
        assert creds.api_key == "demo-key"


class TestIgDiscoveryClient:
    def test_create_session_search_and_get_market(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/session":
                assert request.headers["X-IG-API-KEY"] == "api-key"
                return httpx.Response(
                    200,
                    headers={"CST": "cst-token", "X-SECURITY-TOKEN": "sec-token"},
                    json={"accountType": "CFD"},
                )
            if request.url.path == "/gateway/deal/markets":
                assert request.headers["CST"] == "cst-token"
                assert request.headers["X-SECURITY-TOKEN"] == "sec-token"
                assert request.url.params["searchTerm"] == "Australia 200"
                return httpx.Response(
                    200,
                    json={
                        "markets": [
                            {
                                "epic": "IX.D.AU200.CASH.IP",
                                "instrumentName": "Australia 200 Cash",
                                "instrumentType": "INDICES",
                                "expiry": "DFB",
                                "marketStatus": "TRADEABLE",
                                "delayTime": 0,
                            }
                        ]
                    },
                )
            if request.url.path == "/gateway/deal/markets/IX.D.AU200.CASH.IP":
                return httpx.Response(
                    200,
                    json={
                        "instrument": {
                            "epic": "IX.D.AU200.CASH.IP",
                            "name": "Australia 200 Cash",
                            "type": "INDICES",
                            "expiry": "DFB",
                            "marginFactor": 5,
                            "marginFactorUnit": "PERCENTAGE",
                            "lotSize": 1,
                            "onePipMeans": "AUD 1",
                            "currencies": [{"code": "AUD"}],
                            "openingHours": {
                                "marketTimes": [{"openTime": "08:00", "closeTime": "07:00"}]
                            },
                        },
                        "dealingRules": {"minDealSize": {"value": 1, "unit": "POINTS"}},
                        "snapshot": {"marketStatus": "TRADEABLE"},
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        creds = IgCredentials(api_key="api-key", identifier="user", password="pass")
        client = IgDiscoveryClient(creds, client=_mock_client(handler))

        tokens = client.create_session()
        assert tokens.cst == "cst-token"

        results = client.search_markets("Australia 200")
        assert len(results) == 1
        assert results[0].epic == "IX.D.AU200.CASH.IP"

        details = client.get_market(results[0].epic)
        assert isinstance(details, IgMarketDetails)
        assert details.currency == "AUD"
        assert details.margin_factor == 5.0
        assert details.min_deal_size == 1.0

        patch = client.build_registry_patch(canonical_id="AU200.cash", details=details)
        assert patch["venues"]["ig"]["broker_symbol"] == "IX.D.AU200.CASH.IP"
        assert patch["margin_rate"] == 0.05

    def test_preissued_tokens_skip_login_request(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/gateway/deal/markets":
                assert request.headers["CST"] == "cst"
                assert request.headers["X-SECURITY-TOKEN"] == "sec"
                return httpx.Response(200, json={"markets": []})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        creds = IgCredentials(
            api_key="api-key",
            cst="cst",
            security_token="sec",
        )
        client = IgDiscoveryClient(creds, client=_mock_client(handler))

        results = client.search_markets("Australia 200")
        assert results == []
        assert calls == ["/gateway/deal/markets"]

    def test_http_errors_raise_discovery_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gateway/deal/session":
                return httpx.Response(
                    400,
                    json={"errorCode": "error.public-api.failure.invalid-credentials"},
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        creds = IgCredentials(api_key="api-key", identifier="user", password="bad-pass")
        client = IgDiscoveryClient(creds, client=_mock_client(handler))

        with pytest.raises(Exception, match="invalid-credentials"):
            client.create_session()
