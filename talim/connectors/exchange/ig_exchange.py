"""IG OTC exchange adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
import uuid
from typing import Any

import httpx

from talim.cfd import CfdInstrumentRegistry, load_default_registry
from talim.connectors.exchange.base import BaseExchange, Order, OrderStatus
from talim.connectors.exchange.ig_discovery import (
    IgCredentials,
    IgDiscoveryClient,
    IgDiscoveryError,
)
from talim.models.position import Position


class IgExchangeError(IgDiscoveryError):
    """Raised when the IG exchange adapter cannot fulfil a request."""


@dataclass(frozen=True, slots=True)
class _ResolvedInstrument:
    canonical_id: str
    broker_symbol: str
    expiry: str
    currency_code: str


class IgExchange(IgDiscoveryClient, BaseExchange):
    """IG OTC execution adapter backed by the IG REST API."""

    def __init__(
        self,
        credentials: IgCredentials,
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
        confirm_retries: int = 3,
        confirm_delay_s: float = 0.2,
    ) -> None:
        super().__init__(credentials, client=client)
        self._registry = registry or load_default_registry()
        self._confirm_retries = max(1, confirm_retries)
        self._confirm_delay_s = max(0.0, confirm_delay_s)
        self._broker_to_canonical: dict[str, str] = {}
        for spec in self._registry.list_instruments():
            for venue in spec.venues:
                if venue.venue == "ig" and venue.broker_symbol:
                    self._broker_to_canonical[venue.broker_symbol] = spec.canonical_id
        self._orders_cache: dict[str, Order] = {}
        self._deal_id_by_reference: dict[str, str] = {}
        self._deal_reference_by_order_id: dict[str, str] = {}

    @classmethod
    def from_env(
        cls,
        *,
        environment: str | None = None,
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
        confirm_retries: int = 3,
        confirm_delay_s: float = 0.2,
    ) -> "IgExchange":
        creds = IgCredentials.from_env()
        if environment is not None and environment != creds.environment:
            creds = IgCredentials(
                api_key=creds.api_key,
                environment=environment,
                identifier=creds.identifier,
                password=creds.password,
                cst=creds.cst,
                security_token=creds.security_token,
            )
        return cls(
            credentials=creds,
            registry=registry,
            client=client,
            confirm_retries=confirm_retries,
            confirm_delay_s=confirm_delay_s,
        )

    def place_order(
        self,
        instrument: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: float | None = None,
        strategy: str = "",
    ) -> Order:
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")
        if qty <= 0:
            raise ValueError(f"Invalid qty: {qty}")

        order_type_normalized = order_type.strip().lower()
        if order_type_normalized not in {"market", "limit"}:
            raise ValueError(f"Unsupported order type for IG: {order_type}")

        resolved = self._resolve_instrument(instrument)
        self.create_session()
        self._registry.validate_order_support(
            "ig",
            order_type="market" if order_type_normalized == "market" else "limit",
            working_order=order_type_normalized == "limit",
        )

        deal_reference = self._new_deal_reference()
        if order_type_normalized == "market":
            response = self._client.post(
                "/positions/otc",
                headers=self._headers(authenticated=True, version="2"),
                json={
                    "currencyCode": resolved.currency_code,
                    "dealReference": deal_reference,
                    "direction": self._direction(side),
                    "epic": resolved.broker_symbol,
                    "expiry": resolved.expiry,
                    "forceOpen": False,
                    "guaranteedStop": False,
                    "orderType": "MARKET",
                    "size": qty,
                    "timeInForce": "FILL_OR_KILL",
                },
            )
        else:
            if limit_price is None:
                raise ValueError("IG limit orders require limit_price")
            response = self._client.post(
                "/working-orders/otc",
                headers=self._headers(authenticated=True, version="2"),
                json={
                    "currencyCode": resolved.currency_code,
                    "dealReference": deal_reference,
                    "direction": self._direction(side),
                    "epic": resolved.broker_symbol,
                    "expiry": resolved.expiry,
                    "forceOpen": False,
                    "guaranteedStop": False,
                    "level": limit_price,
                    "size": qty,
                    "timeInForce": "GOOD_TILL_CANCELLED",
                    "type": "LIMIT",
                },
            )
        self._raise_for_status(response, f"place IG {order_type_normalized} order")
        response_payload = response.json()
        deal_reference = str(response_payload.get("dealReference") or deal_reference)

        confirm = self._fetch_confirm(deal_reference)
        order = self._build_order_from_submission(
            canonical_instrument=resolved.canonical_id,
            side=side,
            qty=qty,
            order_type=order_type_normalized,
            limit_price=limit_price,
            strategy=strategy,
            deal_reference=deal_reference,
            confirm=confirm,
        )
        self._cache_order(order, deal_reference)
        return order

    def cancel_order(self, order_id: str) -> bool:
        deal_id = self._resolve_cancel_deal_id(order_id)
        if not deal_id:
            return False
        response = self._client.delete(
            f"/working-orders/otc/{deal_id}",
            headers=self._headers(authenticated=True, version="2"),
        )
        if response.status_code >= 400:
            return False

        for key in {order_id, deal_id}:
            cached = self._orders_cache.get(key)
            if cached is not None:
                cached.status = OrderStatus.CANCELLED
        return True

    def get_positions(self) -> list[Position]:
        self.create_session()
        response = self._client.get(
            "/positions",
            headers=self._headers(authenticated=True, version="2"),
        )
        self._raise_for_status(response, "fetch IG positions")
        payload = response.json()
        positions: list[Position] = []
        for item in payload.get("positions", []):
            market = item.get("market", {})
            raw_position = item.get("position", {})
            qty = float(raw_position.get("size") or 0.0)
            if qty == 0:
                continue
            side = "long" if raw_position.get("direction") == "BUY" else "short"
            entry = float(raw_position.get("level") or 0.0)
            current = float(
                market.get("bid") if side == "long" else market.get("offer") or 0.0
            )
            contract_size = float(raw_position.get("contractSize") or 1.0)
            open_pnl = (current - entry) * qty * contract_size
            if side == "short":
                open_pnl = (entry - current) * qty * contract_size
            epic = market.get("epic", raw_position.get("epic", ""))
            positions.append(
                Position(
                    instrument=self._canonical_or_broker(epic),
                    side=side,
                    qty=qty,
                    entry_price=entry,
                    stop=float(raw_position.get("stopLevel") or 0.0),
                    target=float(raw_position.get("limitLevel") or 0.0),
                    strategy="",
                    open_pnl=open_pnl,
                    entry_time=self._parse_dt(raw_position.get("createdDateUTC")),
                    position_id=str(raw_position.get("dealId") or ""),
                )
            )
        return positions

    def get_account_balance(self) -> dict[str, float]:
        self.create_session()
        response = self._client.get(
            "/accounts",
            headers=self._headers(authenticated=True, version="1"),
        )
        self._raise_for_status(response, "fetch IG accounts")
        payload = response.json()
        accounts = payload.get("accounts", [])
        if not accounts:
            return {}
        preferred = next((acct for acct in accounts if acct.get("preferred")), None)
        active = preferred or next((acct for acct in accounts if acct.get("status") == "ENABLED"), None) or accounts[0]
        currency = active.get("currency") or "USD"
        balances = active.get("balance", {})
        return {currency: float(balances.get("balance") or balances.get("available") or 0.0)}

    def get_order(self, order_id: str) -> Order | None:
        cached = self._orders_cache.get(order_id)
        if cached is not None and cached.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return cached

        deal_id = self._resolve_deal_id(order_id)
        if deal_id:
            working = self._find_working_order(deal_id)
            if working is not None:
                order = self._order_from_working_order(working)
                self._cache_order(order, self._deal_reference_by_order_id.get(order.order_id))
                return order

            position = self._find_position_order(deal_id)
            if position is not None:
                self._cache_order(position, self._deal_reference_by_order_id.get(order_id))
                return position

        if cached is not None:
            return cached

        confirm = self._fetch_confirm(order_id)
        if confirm is not None:
            fallback = self._build_order_from_submission(
                canonical_instrument=cached.instrument if cached else order_id,
                side=cached.side if cached else "buy",
                qty=cached.qty if cached else 0.0,
                order_type=cached.order_type if cached else "market",
                limit_price=cached.limit_price if cached else None,
                strategy=cached.strategy if cached else "",
                deal_reference=order_id,
                confirm=confirm,
            )
            self._cache_order(fallback, order_id)
            return fallback
        return None

    def _resolve_instrument(self, instrument: str) -> _ResolvedInstrument:
        spec = self._registry.get(instrument)
        mapping = self._registry.resolve_mapping(instrument, "ig")
        if not mapping.broker_symbol:
            raise IgExchangeError(f"instrument {instrument!r} has no resolved IG broker symbol")
        expiry = mapping.expiry or ("-" if instrument.endswith(".cash") else "")
        if not expiry:
            raise IgExchangeError(f"instrument {instrument!r} has no IG expiry configured")
        return _ResolvedInstrument(
            canonical_id=spec.canonical_id,
            broker_symbol=mapping.broker_symbol,
            expiry=expiry,
            currency_code=spec.quote_currency,
        )

    def _canonical_or_broker(self, broker_symbol: str) -> str:
        return self._broker_to_canonical.get(broker_symbol, broker_symbol)

    def _new_deal_reference(self) -> str:
        return f"talim-{uuid.uuid4().hex[:18]}"

    @staticmethod
    def _direction(side: str) -> str:
        return "BUY" if side == "buy" else "SELL"

    def _fetch_confirm(self, deal_reference: str) -> dict[str, Any] | None:
        self.create_session()
        for attempt in range(self._confirm_retries):
            response = self._client.get(
                f"/confirms/{deal_reference}",
                headers=self._headers(authenticated=True, version="1"),
            )
            if response.status_code == 200:
                payload = response.json()
                self._cache_confirm(deal_reference, payload)
                return payload
            if response.status_code == 404:
                if attempt == self._confirm_retries - 1:
                    return None
            elif response.status_code < 500:
                self._raise_for_status(response, f"confirm IG deal {deal_reference}")
            if attempt < self._confirm_retries - 1 and self._confirm_delay_s:
                time.sleep(self._confirm_delay_s)
        return None

    def _cache_confirm(self, deal_reference: str, payload: dict[str, Any]) -> None:
        deal_id = self._extract_confirm_deal_id(payload)
        if deal_id:
            self._deal_id_by_reference[deal_reference] = deal_id
            self._deal_reference_by_order_id[deal_id] = deal_reference

    @staticmethod
    def _extract_confirm_deal_id(payload: dict[str, Any]) -> str | None:
        affected = payload.get("affectedDeals")
        if isinstance(affected, list) and affected:
            deal_id = affected[0].get("dealId")
            if deal_id:
                return str(deal_id)
        if payload.get("dealId"):
            return str(payload["dealId"])
        return None

    def _build_order_from_submission(
        self,
        *,
        canonical_instrument: str,
        side: str,
        qty: float,
        order_type: str,
        limit_price: float | None,
        strategy: str,
        deal_reference: str,
        confirm: dict[str, Any] | None,
    ) -> Order:
        deal_id = self._extract_confirm_deal_id(confirm or {}) or deal_reference
        status = OrderStatus.OPEN if order_type == "limit" else OrderStatus.PENDING
        fill_price = None
        fill_time = None

        if confirm is not None:
            deal_status = (confirm.get("dealStatus") or "").upper()
            if deal_status and deal_status != "ACCEPTED":
                status = OrderStatus.REJECTED
            elif order_type == "market":
                status = OrderStatus.FILLED
                fill_price = self._maybe_float(confirm.get("level"))
                fill_time = datetime.now(tz=timezone.utc)
            else:
                status = OrderStatus.OPEN

        return Order(
            order_id=deal_id,
            instrument=canonical_instrument,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            status=status,
            fill_price=fill_price,
            fill_time=fill_time,
            strategy=strategy,
        )

    def _cache_order(self, order: Order, deal_reference: str | None) -> None:
        self._orders_cache[order.order_id] = order
        if deal_reference:
            self._orders_cache[deal_reference] = order
            self._deal_reference_by_order_id[order.order_id] = deal_reference
            if order.order_id != deal_reference:
                self._deal_id_by_reference[deal_reference] = order.order_id

    def _resolve_deal_id(self, order_id: str) -> str | None:
        if order_id in self._deal_id_by_reference:
            return self._deal_id_by_reference[order_id]
        if order_id in self._deal_reference_by_order_id:
            return order_id
        confirm = self._fetch_confirm(order_id)
        if confirm is None:
            return order_id if order_id in self._orders_cache else None
        return self._extract_confirm_deal_id(confirm) or order_id

    def _resolve_cancel_deal_id(self, order_id: str) -> str | None:
        resolved = self._resolve_deal_id(order_id)
        if resolved is None:
            return None
        working = self._find_working_order(resolved)
        if working is None:
            return None
        return resolved

    def _find_working_order(self, deal_id: str) -> dict[str, Any] | None:
        self.create_session()
        response = self._client.get(
            "/working-orders",
            headers=self._headers(authenticated=True, version="2"),
        )
        self._raise_for_status(response, "fetch IG working orders")
        payload = response.json()
        for item in payload.get("workingOrders", payload.get("working-orders", [])):
            data = item.get("workingOrderData", item.get("working-order-data", {}))
            if str(data.get("dealId") or "") == deal_id:
                return item
        return None

    def _order_from_working_order(self, item: dict[str, Any]) -> Order:
        data = item.get("workingOrderData", item.get("working-order-data", {}))
        epic = data.get("epic") or item.get("marketData", {}).get("epic", "")
        order_type = "limit"
        raw_type = (data.get("orderType") or data.get("requestType") or "").upper()
        if raw_type == "STOP":
            order_type = "stop"
        return Order(
            order_id=str(data.get("dealId")),
            instrument=self._canonical_or_broker(epic),
            side="buy" if data.get("direction") == "BUY" else "sell",
            qty=float(data.get("orderSize") or data.get("size") or 0.0),
            order_type=order_type,
            limit_price=self._maybe_float(data.get("orderLevel") or data.get("level")),
            status=OrderStatus.OPEN,
        )

    def _find_position_order(self, deal_id: str) -> Order | None:
        for position in self.get_positions():
            if position.position_id == deal_id:
                return Order(
                    order_id=deal_id,
                    instrument=position.instrument,
                    side="buy" if position.side == "long" else "sell",
                    qty=position.qty,
                    order_type="market",
                    status=OrderStatus.FILLED,
                    fill_price=position.entry_price,
                    fill_time=position.entry_time,
                )
        return None

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        cleaned = value.replace("/", "-").replace(" ", "T")
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)
