"""FOREX.com / StoneX TradingApi discovery client used ahead of the full exchange adapter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx


FOREXCOM_BASE_URLS = {
    "live": "https://ciapi.cityindex.com/TradingApi",
    "demo": "https://ciapi.cityindex.com/TradingApi",
}


class ForexcomDiscoveryError(RuntimeError):
    """Raised when FOREX.com auth or market discovery fails."""


@dataclass(frozen=True, slots=True)
class ForexcomSession:
    user_name: str
    session: str


@dataclass(frozen=True, slots=True)
class ForexcomCredentials:
    login: str
    password: str
    app_key: str
    environment: str = "live"

    def __post_init__(self) -> None:
        env = self.environment.strip().lower()
        if env not in FOREXCOM_BASE_URLS:
            raise ValueError(
                f"invalid FOREX.com environment {self.environment!r}; "
                f"must be one of {sorted(FOREXCOM_BASE_URLS)}"
            )
        object.__setattr__(self, "environment", env)
        if not (self.login and self.password and self.app_key):
            raise ValueError("FOREX.com credentials require login, password, and app_key")

    @classmethod
    def from_env(cls, prefix: str = "FOREXDOTCOM") -> "ForexcomCredentials":
        login = os.environ.get(f"{prefix}_LOGIN")
        password = os.environ.get(f"{prefix}_PASSWORD")
        app_key = os.environ.get(f"{prefix}_APP_KEY")
        environment = os.environ.get(f"{prefix}_ENVIRONMENT", "live").strip().lower()
        if not login or not password or not app_key:
            raise ValueError(
                f"missing one of {prefix}_LOGIN, {prefix}_PASSWORD, {prefix}_APP_KEY"
            )
        return cls(login=login, password=password, app_key=app_key, environment=environment)


@dataclass(frozen=True, slots=True)
class ForexcomMarketSummary:
    market_id: str
    name: str
    weighting: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ForexcomMarketSummary":
        return cls(
            market_id=str(payload.get("MarketId", "")),
            name=str(payload.get("Name", "")),
            weighting=_maybe_int(payload.get("Weighting")),
        )


@dataclass(frozen=True, slots=True)
class ForexcomMarketDetails:
    market_id: str
    name: str
    market_settings_type: str
    market_underlying_type: str
    currency_iso_code: str
    margin_factor: float | None
    margin_factor_units: int | None
    increment_size: float | None
    web_min_size: float | None
    price_decimal_places: int | None
    allow_guaranteed_orders: bool
    guaranteed_order_premium: float | None
    guaranteed_order_min_distance: float | None
    expiry_utc_ms: int | None
    market_24h: bool
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, currency_iso_code: str = "") -> "ForexcomMarketDetails":
        info = payload.get("MarketInformation", payload)
        return cls(
            market_id=str(info.get("MarketId", "")),
            name=str(info.get("Name", "")),
            market_settings_type=str(info.get("MarketSettingsType", "")),
            market_underlying_type=str(info.get("MarketUnderlyingType", "")),
            currency_iso_code=currency_iso_code,
            margin_factor=_maybe_float(info.get("MarginFactor")),
            margin_factor_units=_maybe_int(info.get("MarginFactorUnits")),
            increment_size=_maybe_float(info.get("IncrementSize")),
            web_min_size=_maybe_float(info.get("WebMinSize")),
            price_decimal_places=_maybe_int(info.get("PriceDecimalPlaces")),
            allow_guaranteed_orders=bool(info.get("AllowGuaranteedOrders", False)),
            guaranteed_order_premium=_maybe_float(info.get("GuaranteedOrderPremium")),
            guaranteed_order_min_distance=_maybe_float(info.get("GuaranteedOrderMinDistance")),
            expiry_utc_ms=_parse_dotnet_date_ms(info.get("ExpiryUtc")),
            market_24h=bool(info.get("Market24H", False)),
            raw=payload,
        )


def _maybe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dotnet_date_ms(value: Any) -> int | None:
    """Parse a /Date(1234567890000)/ wire format into epoch milliseconds."""
    if not value or not isinstance(value, str):
        return None
    start = value.find("(")
    end = value.find(")")
    if start == -1 or end == -1 or end <= start:
        return None
    body = value[start + 1 : end]
    # body may be "1234567890000" or "1234567890000+1000"
    for sep in ("+", "-"):
        idx = body.find(sep, 1)
        if idx > 0:
            body = body[:idx]
            break
    try:
        return int(body)
    except ValueError:
        return None


class ForexcomDiscoveryClient:
    """Thin FOREX.com REST client for login and market metadata lookup."""

    def __init__(
        self,
        credentials: ForexcomCredentials,
        client: httpx.Client | None = None,
    ) -> None:
        self.credentials = credentials
        self._client = client or httpx.Client(
            base_url=FOREXCOM_BASE_URLS[credentials.environment],
            timeout=30.0,
        )
        self._owns_client = client is None
        self._session: ForexcomSession | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ForexcomDiscoveryClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def session_tokens(self) -> ForexcomSession | None:
        return self._session

    def create_session(self) -> ForexcomSession:
        if self._session is not None:
            return self._session
        response = self._client.post(
            "/session",
            headers=self._headers(),
            json={
                "UserName": self.credentials.login,
                "Password": self.credentials.password,
                "AppKey": self.credentials.app_key,
            },
        )
        self._raise_for_status(response, "create FOREX.com session")
        payload = response.json()
        session_id = payload.get("Session")
        if not session_id or payload.get("StatusCode") != 1:
            raise ForexcomDiscoveryError(
                f"FOREX.com session response did not include a valid Session: {payload!r}"
            )
        self._session = ForexcomSession(user_name=self.credentials.login, session=str(session_id))
        return self._session

    def validate_session(self) -> bool:
        session = self.create_session()
        response = self._client.post(
            "/session/validate",
            headers=self._headers(authenticated=True),
            json={"UserName": session.user_name, "Session": session.session},
        )
        if response.status_code == 401:
            self._session = None
            return False
        self._raise_for_status(response, "validate FOREX.com session")
        return bool(response.json().get("IsAuthenticated", False))

    def logout(self) -> None:
        if self._session is None:
            return
        session = self._session
        try:
            self._client.post(
                "/session/deleteSession",
                headers=self._headers(authenticated=True),
                json={"UserName": session.user_name, "Session": session.session},
            )
        finally:
            self._session = None

    def search_markets(self, query: str, max_results: int = 20) -> list[ForexcomMarketSummary]:
        self.create_session()
        response = self._client.get(
            "/cfd/markets",
            params={"MarketName": query, "MaxResults": max_results},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"search FOREX.com markets for {query!r}")
        payload = response.json()
        return [ForexcomMarketSummary.from_payload(item) for item in payload.get("Markets", [])]

    def get_market(self, market_id: str, *, currency_iso_code: str = "") -> ForexcomMarketDetails:
        self.create_session()
        response = self._client.get(
            f"/market/{market_id}/information",
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"fetch FOREX.com market {market_id!r}")
        return ForexcomMarketDetails.from_payload(response.json(), currency_iso_code=currency_iso_code)

    def build_registry_patch(
        self,
        *,
        canonical_id: str,
        details: ForexcomMarketDetails,
        lookup_hint: str | None = None,
    ) -> dict[str, Any]:
        # MarginFactorUnits 26 = PERCENTAGE in the StoneX codec; anything else needs manual review.
        margin_rate: float | None
        if details.margin_factor is not None and details.margin_factor_units == 26:
            margin_rate = details.margin_factor / 100.0
        else:
            margin_rate = None

        return {
            "canonical_id": canonical_id,
            "display_name": details.name,
            "asset_class": "index_cfd" if details.market_underlying_type == "Index" else details.market_settings_type.lower(),
            "quote_currency": details.currency_iso_code,
            "tick_size": details.increment_size,
            "price_precision": details.price_decimal_places,
            "min_size": details.web_min_size,
            "size_step": details.increment_size,
            "margin_rate": margin_rate,
            "venues": {
                "forexcom": {
                    "lookup_hint": lookup_hint or details.name,
                    "broker_symbol": details.market_id,
                    "market_id": details.market_id,
                    "expiry": "-" if details.expiry_utc_ms is None else "fwd",
                    "venue_display_name": details.name,
                    "product_type": "index_cfd" if details.market_underlying_type == "Index" else None,
                    "notes": (
                        "Discovered via FOREX.com market discovery. Review session metadata "
                        "and step-margin bands before enabling trading."
                    ),
                }
            },
        }

    def _headers(self, *, authenticated: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if authenticated:
            if self._session is None:
                raise ForexcomDiscoveryError(
                    "authenticated request attempted before session bootstrap"
                )
            headers["UserName"] = self._session.user_name
            headers["Session"] = self._session.session
        return headers

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if isinstance(payload, dict):
                code = payload.get("ErrorCode") or payload.get("StatusCode")
                message = payload.get("ErrorMessage")
                if code and message:
                    detail = f" ({code}: {message})"
                elif code:
                    detail = f" ({code})"
            raise ForexcomDiscoveryError(f"failed to {action}{detail}: {response.text}") from exc
