"""IG market discovery client used ahead of a full exchange adapter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx


IG_BASE_URLS = {
    "demo": "https://demo-api.ig.com/gateway/deal",
    "live": "https://api.ig.com/gateway/deal",
}


class IgDiscoveryError(RuntimeError):
    """Raised when IG auth or market discovery fails."""


@dataclass(frozen=True, slots=True)
class IgSessionTokens:
    cst: str
    security_token: str


@dataclass(frozen=True, slots=True)
class IgCredentials:
    api_key: str
    environment: str = "demo"
    identifier: str | None = None
    password: str | None = None
    cst: str | None = None
    security_token: str | None = None

    def __post_init__(self) -> None:
        env = self.environment.strip().lower()
        if env not in IG_BASE_URLS:
            raise ValueError(
                f"invalid IG environment {self.environment!r}; "
                f"must be one of {sorted(IG_BASE_URLS)}"
            )
        object.__setattr__(self, "environment", env)
        if self.has_session_tokens:
            return
        if not (self.identifier and self.password):
            raise ValueError(
                "IG credentials require either identifier/password or CST + "
                "X-SECURITY-TOKEN session tokens"
            )

    @property
    def has_session_tokens(self) -> bool:
        return bool(self.cst and self.security_token)

    @classmethod
    def from_env(cls, prefix: str = "IG") -> "IgCredentials":
        environment = os.environ.get(f"{prefix}_ENVIRONMENT", "demo").strip().lower()
        demo_api_key = os.environ.get(f"{prefix}_DEMO_API_KEY")
        default_api_key = os.environ.get(f"{prefix}_API_KEY")
        api_key = demo_api_key if environment == "demo" and demo_api_key else default_api_key or demo_api_key
        if not api_key:
            raise ValueError(f"missing {prefix}_API_KEY")
        return cls(
            api_key=api_key,
            environment=environment,
            identifier=(
                os.environ.get(f"{prefix}_IDENTIFIER")
                or os.environ.get(f"{prefix}_DEMO_LOGIN")
            ),
            password=(
                os.environ.get(f"{prefix}_PASSWORD")
                or os.environ.get(f"{prefix}_DEMO_PASSWORD")
            ),
            cst=os.environ.get(f"{prefix}_CST"),
            security_token=os.environ.get(f"{prefix}_SECURITY_TOKEN"),
        )


@dataclass(frozen=True, slots=True)
class IgMarketSummary:
    epic: str
    instrument_name: str
    instrument_type: str
    expiry: str
    market_status: str
    delay_time: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IgMarketSummary":
        instrument = payload.get("instrument", {})
        snapshot = payload.get("snapshot", {})
        return cls(
            epic=payload.get("epic", instrument.get("epic", "")),
            instrument_name=payload.get("instrumentName", instrument.get("name", "")),
            instrument_type=payload.get("instrumentType", instrument.get("type", "")),
            expiry=payload.get("expiry", instrument.get("expiry", "")),
            market_status=payload.get("marketStatus", snapshot.get("marketStatus", "")),
            delay_time=_maybe_int(payload.get("delayTime", instrument.get("delayTime"))),
        )


@dataclass(frozen=True, slots=True)
class IgMarketDetails:
    epic: str
    instrument_name: str
    instrument_type: str
    expiry: str
    currency: str | None
    market_status: str
    margin_factor: float | None
    margin_factor_unit: str | None
    min_deal_size: float | None
    lot_size: float | None
    one_pip_means: str | None
    opening_hours: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IgMarketDetails":
        instrument = payload.get("instrument", {})
        snapshot = payload.get("snapshot", {})
        dealing_rules = payload.get("dealingRules", {})
        currencies = instrument.get("currencies", [])
        currency = None
        if currencies:
            currency = currencies[0].get("code")
        return cls(
            epic=instrument.get("epic", payload.get("epic", "")),
            instrument_name=instrument.get("name", payload.get("instrumentName", "")),
            instrument_type=instrument.get("type", payload.get("instrumentType", "")),
            expiry=instrument.get("expiry", payload.get("expiry", "")),
            currency=currency,
            market_status=snapshot.get("marketStatus", ""),
            margin_factor=_maybe_float(instrument.get("marginFactor")),
            margin_factor_unit=instrument.get("marginFactorUnit"),
            min_deal_size=_extract_value(dealing_rules.get("minDealSize")),
            lot_size=_maybe_float(instrument.get("lotSize")),
            one_pip_means=instrument.get("onePipMeans"),
            opening_hours=instrument.get("openingHours") or {},
            raw=payload,
        )


def _maybe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _extract_value(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    return _maybe_float(value)


class IgDiscoveryClient:
    """Thin IG REST client for login and market metadata lookup."""

    def __init__(
        self,
        credentials: IgCredentials,
        client: httpx.Client | None = None,
    ) -> None:
        self.credentials = credentials
        self._client = client or httpx.Client(
            base_url=IG_BASE_URLS[credentials.environment],
            timeout=30.0,
        )
        self._owns_client = client is None
        self._tokens: IgSessionTokens | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "IgDiscoveryClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def session_tokens(self) -> IgSessionTokens | None:
        return self._tokens

    def create_session(self) -> IgSessionTokens:
        if self._tokens is not None:
            return self._tokens
        if self.credentials.has_session_tokens:
            self._tokens = IgSessionTokens(
                cst=self.credentials.cst or "",
                security_token=self.credentials.security_token or "",
            )
            return self._tokens

        response = self._client.post(
            "/session",
            headers=self._headers(version="2"),
            json={
                "identifier": self.credentials.identifier,
                "password": self.credentials.password,
            },
        )
        self._raise_for_status(response, "create session")
        cst = response.headers.get("CST")
        security = response.headers.get("X-SECURITY-TOKEN")
        if not cst or not security:
            raise IgDiscoveryError("IG session response did not include CST and X-SECURITY-TOKEN")
        self._tokens = IgSessionTokens(cst=cst, security_token=security)
        return self._tokens

    def search_markets(self, query: str) -> list[IgMarketSummary]:
        self.create_session()
        response = self._client.get(
            "/markets",
            params={"searchTerm": query},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"search markets for {query!r}")
        payload = response.json()
        return [IgMarketSummary.from_payload(item) for item in payload.get("markets", [])]

    def get_market(self, epic: str) -> IgMarketDetails:
        self.create_session()
        response = self._client.get(
            f"/markets/{epic}",
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"fetch market {epic!r}")
        return IgMarketDetails.from_payload(response.json())

    def build_registry_patch(
        self,
        *,
        canonical_id: str,
        details: IgMarketDetails,
        lookup_hint: str | None = None,
    ) -> dict[str, Any]:
        margin_rate = None
        if details.margin_factor is not None and (details.margin_factor_unit or "").upper() == "PERCENTAGE":
            margin_rate = details.margin_factor / 100.0

        product_type = (details.instrument_type or "").lower().replace(" ", "_")
        return {
            "canonical_id": canonical_id,
            "display_name": details.instrument_name,
            "asset_class": product_type or "cfd",
            "quote_currency": details.currency or "",
            "min_size": details.min_deal_size,
            "margin_rate": margin_rate,
            "venues": {
                "ig": {
                    "lookup_hint": lookup_hint or details.instrument_name,
                    "broker_symbol": details.epic,
                    "market_id": details.epic,
                    "expiry": details.expiry,
                    "venue_display_name": details.instrument_name,
                    "product_type": product_type or None,
                    "notes": (
                        "Discovered via IG market discovery. Review tick size, point value, "
                        "and session metadata before enabling trading."
                    ),
                }
            },
        }

    def _headers(self, *, version: str = "1", authenticated: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json; charset=UTF-8",
            "Content-Type": "application/json; charset=UTF-8",
            "X-IG-API-KEY": self.credentials.api_key,
            "VERSION": version,
        }
        if authenticated:
            if self._tokens is None:
                raise IgDiscoveryError("authenticated request attempted before session bootstrap")
            headers["CST"] = self._tokens.cst
            headers["X-SECURITY-TOKEN"] = self._tokens.security_token
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
            if isinstance(payload, dict) and payload.get("errorCode"):
                detail = f" ({payload['errorCode']})"
            raise IgDiscoveryError(f"failed to {action}{detail}: {response.text}") from exc
