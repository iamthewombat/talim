"""FOREX.com (StoneX TradingApi) OTC exchange adapter.

Implements the Phase 10 BaseExchange contract on top of the broker-neutral CFD
registry. The StoneX TradingApi uses a hedging (FIFO-stack) position model: each
`newtradeorder` creates a distinct OpenPosition row, and closes are applied
FIFO. This adapter aggregates those rows into one logical `Position` per
(canonical_instrument, side) so the strategy/risk layer sees the same shape it
sees for IG's netted model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from typing import Any

import httpx

from talim.cfd import CfdInstrumentRegistry, load_default_registry
from talim.connectors.exchange.base import BaseExchange, Order, OrderStatus
from talim.connectors.exchange.forexcom_discovery import (
    ForexcomCredentials,
    ForexcomDiscoveryClient,
    ForexcomDiscoveryError,
)
from talim.models.position import Position


class ForexcomExchangeError(ForexcomDiscoveryError):
    """Raised when the FOREX.com exchange adapter cannot fulfil a request."""


@dataclass(frozen=True, slots=True)
class _ResolvedInstrument:
    canonical_id: str
    market_id: str
    currency_code: str


@dataclass(frozen=True, slots=True)
class _Quote:
    bid: float
    offer: float
    audit_id: str


_DIRECTION_MAP = {"buy": "buy", "sell": "sell"}


class ForexcomExchange(ForexcomDiscoveryClient, BaseExchange):
    """FOREX.com OTC execution adapter backed by the StoneX TradingApi."""

    def __init__(
        self,
        credentials: ForexcomCredentials,
        trading_account_id: int | str,
        client_account_id: int | str,
        *,
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(credentials, client=client)
        self._registry = registry or load_default_registry()
        self._trading_account_id = int(trading_account_id)
        self._client_account_id = int(client_account_id)
        self._orders_cache: dict[str, Order] = {}
        self._instrument_by_market_id: dict[str, str] = {}
        for spec in self._registry.list_instruments():
            for venue in spec.venues:
                if venue.venue == "forexcom" and venue.market_id:
                    self._instrument_by_market_id[venue.market_id] = spec.canonical_id

    @classmethod
    def from_env(
        cls,
        *,
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> "ForexcomExchange":
        creds = ForexcomCredentials.from_env()
        import os

        trading_account_id = os.environ.get("FOREXDOTCOM_TRADING_ACCOUNT_ID")
        client_account_id = os.environ.get("FOREXDOTCOM_CLIENT_ACCOUNT_ID")
        instance = cls.__new__(cls)
        ForexcomDiscoveryClient.__init__(instance, creds, client=client)
        instance._registry = registry or load_default_registry()
        instance._orders_cache = {}
        instance._instrument_by_market_id = {}
        for spec in instance._registry.list_instruments():
            for venue in spec.venues:
                if venue.venue == "forexcom" and venue.market_id:
                    instance._instrument_by_market_id[venue.market_id] = spec.canonical_id
        if trading_account_id and client_account_id:
            instance._trading_account_id = int(trading_account_id)
            instance._client_account_id = int(client_account_id)
        else:
            instance.create_session()
            account = instance._fetch_account_metadata()
            instance._trading_account_id = int(account["TradingAccountId"])
            instance._client_account_id = int(account["ClientAccountId"])
        return instance

    def place_order(
        self,
        instrument: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: float | None = None,
        strategy: str = "",
        stop_price: float | None = None,
        target_price: float | None = None,
    ) -> Order:
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")
        if qty <= 0:
            raise ValueError(f"Invalid qty: {qty}")

        order_type_normalized = order_type.strip().lower()
        if order_type_normalized not in {"market", "limit"}:
            raise ValueError(f"Unsupported order type for FOREX.com: {order_type}")

        resolved = self._resolve_instrument(instrument)
        self.create_session()
        self._registry.validate_order_support(
            "forexcom",
            order_type=order_type_normalized,
            working_order=order_type_normalized == "limit",
            attached_stop=stop_price is not None,
            attached_limit=target_price is not None,
        )

        if order_type_normalized == "market":
            quote = self._fetch_quote(resolved.market_id)
            payload = {
                "MarketId": int(resolved.market_id),
                "Direction": _DIRECTION_MAP[side],
                "Quantity": qty,
                "TradingAccountId": self._trading_account_id,
                "BidPrice": quote.bid,
                "OfferPrice": quote.offer,
                "AuditId": quote.audit_id,
            }
            self._add_if_done(
                payload,
                close_side="sell" if side == "buy" else "buy",
                qty=qty,
                stop_price=stop_price,
                target_price=target_price,
            )
            response = self._client.post(
                "/order/newtradeorder",
                headers=self._headers(authenticated=True),
                json=payload,
            )
            self._raise_for_status(response, "place FOREX.com market order")
            response_payload = response.json()
            return self._cache_and_return(
                canonical_instrument=resolved.canonical_id,
                side=side,
                qty=qty,
                order_type=order_type_normalized,
                limit_price=None,
                strategy=strategy,
                stop_price=stop_price,
                target_price=target_price,
                response_payload=response_payload,
                quote=quote,
            )

        if limit_price is None:
            raise ValueError("FOREX.com limit orders require limit_price")
        payload = {
            "MarketId": int(resolved.market_id),
            "Direction": _DIRECTION_MAP[side],
            "Quantity": qty,
            "TradingAccountId": self._trading_account_id,
            "TriggerPrice": limit_price,
            "OrderId": 0,
            "Applicability": "GTC",
        }
        self._add_if_done(
            payload,
            close_side="sell" if side == "buy" else "buy",
            qty=qty,
            stop_price=stop_price,
            target_price=target_price,
        )
        response = self._client.post(
            "/order/newstoplimitorder",
            headers=self._headers(authenticated=True),
            json=payload,
        )
        self._raise_for_status(response, "place FOREX.com limit order")
        response_payload = response.json()
        return self._cache_and_return(
            canonical_instrument=resolved.canonical_id,
            side=side,
            qty=qty,
            order_type=order_type_normalized,
            limit_price=limit_price,
            strategy=strategy,
            stop_price=stop_price,
            target_price=target_price,
            response_payload=response_payload,
            quote=None,
        )

    def close_position(
        self,
        position: Position,
        qty: float | None = None,
        strategy: str = "",
    ) -> Order:
        close_qty = position.qty if qty is None else qty
        if close_qty <= 0:
            raise ValueError(f"Invalid close qty: {close_qty}")

        lots = self._fetch_open_position_lots(position.instrument, position.side)
        remaining = close_qty
        order_ids: list[str] = []
        last_payload: dict[str, Any] = {}
        for lot in lots:
            if remaining <= 1e-9:
                break
            lot_qty = float(lot.get("Quantity") or 0.0)
            if lot_qty <= 0:
                continue
            this_qty = min(remaining, lot_qty)
            market_id = str(lot.get("MarketId") or "")
            quote = self._fetch_quote(market_id)
            order_id = str(lot.get("OrderId") or "")
            response = self._client.post(
                "/order/close",
                headers=self._headers(authenticated=True),
                json={
                    "OrderId": int(order_id),
                    "MarketId": int(market_id),
                    "Quantity": this_qty,
                    "TradingAccountId": self._trading_account_id,
                    "BidPrice": quote.bid,
                    "OfferPrice": quote.offer,
                    "AuditId": quote.audit_id,
                },
            )
            try:
                self._raise_for_status(response, "close FOREX.com open position")
            except ForexcomDiscoveryError:
                if response.status_code in {404, 405}:
                    return self._close_position_with_opposite_market_order(
                        position,
                        close_qty=close_qty,
                        strategy=strategy,
                    )
                raise
            last_payload = response.json()
            if not self._response_accepted(last_payload):
                return Order(
                    order_id=order_id,
                    instrument=position.instrument,
                    side="sell" if position.side == "long" else "buy",
                    qty=this_qty,
                    order_type="market",
                    status=OrderStatus.REJECTED,
                    strategy=strategy or position.strategy,
                )
            order_ids.append(order_id)
            remaining -= this_qty

        if remaining > 1e-9:
            raise ForexcomExchangeError(
                f"not enough open {position.side} {position.instrument} qty to close {close_qty}"
            )

        order_id = ",".join(order_ids) or str(last_payload.get("OrderId") or uuid.uuid4().hex)
        close_side = "sell" if position.side == "long" else "buy"
        order = Order(
            order_id=order_id,
            instrument=position.instrument,
            side=close_side,
            qty=close_qty,
            order_type="market",
            status=OrderStatus.FILLED,
            fill_time=datetime.now(tz=timezone.utc),
            strategy=strategy or position.strategy,
        )
        self._orders_cache[order_id] = order
        return order

    def _close_position_with_opposite_market_order(
        self,
        position: Position,
        *,
        close_qty: float,
        strategy: str = "",
    ) -> Order:
        """Close FIFO-stack accounts by submitting the exact opposite order.

        Some FOREX.com/CityIndex demo hosts no longer expose the documented
        /order/close route. On PositionMethodId=1/FIFO accounts, an opposite
        market order for the open quantity closes the oldest matching lot.
        """
        close_side = "sell" if position.side == "long" else "buy"
        return self.place_order(
            instrument=position.instrument,
            side=close_side,
            qty=close_qty,
            order_type="market",
            strategy=strategy or position.strategy,
        )

    def cancel_order(self, order_id: str) -> bool:
        self.create_session()
        try:
            order_id_int = int(order_id)
        except (TypeError, ValueError):
            return False
        response = self._client.post(
            "/order/cancel",
            headers=self._headers(authenticated=True),
            json={
                "OrderId": order_id_int,
                "TradingAccountId": self._trading_account_id,
            },
        )
        if response.status_code >= 400:
            return False
        payload = response.json()
        accepted = False
        for action in payload.get("Actions", []):
            if action.get("Status") == 1:  # 1 == Accepted in StoneX status codec
                accepted = True
                break
        if accepted:
            cached = self._orders_cache.get(order_id)
            if cached is not None:
                cached.status = OrderStatus.CANCELLED
        return accepted

    def get_positions(self) -> list[Position]:
        self.create_session()
        response = self._client.get(
            "/order/openpositions",
            params={"TradingAccountId": self._trading_account_id},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, "fetch FOREX.com open positions")
        payload = response.json()

        return self._positions_from_lots(payload.get("OpenPositions", []))

    def _positions_from_lots(self, lots_payload: list[dict[str, Any]]) -> list[Position]:
        # FIFO-stack → single logical position per (canonical_instrument, side)
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in lots_payload:
            market_id = str(item.get("MarketId", ""))
            canonical = self._instrument_by_market_id.get(market_id, market_id)
            direction = str(item.get("Direction", "")).lower()
            side = "long" if direction == "buy" else "short"
            buckets.setdefault((canonical, side), []).append(item)

        positions: list[Position] = []
        for (canonical, side), lots in buckets.items():
            qty = sum(float(lot.get("Quantity") or 0.0) for lot in lots)
            if qty <= 0:
                continue
            notional = sum(
                float(lot.get("Quantity") or 0.0) * float(lot.get("Price") or 0.0)
                for lot in lots
            )
            vwap = notional / qty if qty else 0.0
            current_price = float(
                lots[-1].get("CurrentPrice") or lots[-1].get("Price") or 0.0
            )
            open_pnl = (current_price - vwap) * qty
            if side == "short":
                open_pnl = (vwap - current_price) * qty
            positions.append(
                Position(
                    instrument=canonical,
                    side=side,
                    qty=qty,
                    entry_price=vwap,
                    stop=0.0,
                    target=0.0,
                    strategy="",
                    open_pnl=open_pnl,
                    entry_time=self._parse_dt(lots[0].get("LastChangedDateTimeUtc")),
                    position_id=str(lots[0].get("OrderId") or ""),
                )
            )
        return positions

    def get_account_balance(self) -> dict[str, float]:
        self.create_session()
        response = self._client.get(
            "/margin/clientaccountmargin",
            params={"ClientAccountId": self._client_account_id},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, "fetch FOREX.com margin")
        payload = response.json()
        currency = str(payload.get("CurrencyIsoCode") or "AUD")
        return {currency: float(payload.get("TradableFunds") or payload.get("Cash") or 0.0)}

    def get_order(self, order_id: str) -> Order | None:
        cached = self._orders_cache.get(order_id)
        if cached is not None and cached.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }:
            return cached

        self.create_session()
        response = self._client.get(
            f"/order/{order_id}",
            params={"TradingAccountId": self._trading_account_id},
            headers=self._headers(authenticated=True),
        )
        if response.status_code == 404:
            return cached
        self._raise_for_status(response, f"fetch FOREX.com order {order_id}")
        payload = response.json().get("Order", {})
        if not payload:
            return cached

        order = self._order_from_payload(payload, fallback=cached)
        self._orders_cache[order.order_id] = order
        return order

    def _resolve_instrument(self, instrument: str) -> _ResolvedInstrument:
        spec = self._registry.get(instrument)
        mapping = self._registry.resolve_mapping(instrument, "forexcom")
        if not mapping.market_id:
            raise ForexcomExchangeError(
                f"instrument {instrument!r} has no resolved FOREX.com market id"
            )
        return _ResolvedInstrument(
            canonical_id=spec.canonical_id,
            market_id=str(mapping.market_id),
            currency_code=spec.quote_currency,
        )

    def _fetch_quote(self, market_id: str) -> _Quote:
        response = self._client.get(
            f"/market/{market_id}/tickhistory",
            params={"PriceTicks": 1},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"fetch FOREX.com quote for market {market_id}")
        payload = response.json()
        ticks = payload.get("PriceTicks", [])
        if not ticks:
            raise ForexcomExchangeError(f"no price ticks returned for market {market_id}")
        tick = ticks[-1]
        price = float(tick.get("Price") or 0.0)
        bid = float(tick.get("Bid") or price)
        offer = float(tick.get("Offer") or price)
        # AuditId is only available on the streaming subscription; pass the tick
        # timestamp ms as a stable per-tick token — the server will revalidate.
        audit_id = str(tick.get("AuditId") or self._extract_date_ms(tick.get("TickDate")) or "0")
        return _Quote(bid=bid, offer=offer, audit_id=audit_id)

    def _fetch_open_position_lots(
        self,
        canonical_instrument: str,
        side: str,
    ) -> list[dict[str, Any]]:
        self.create_session()
        response = self._client.get(
            "/order/openpositions",
            params={"TradingAccountId": self._trading_account_id},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, "fetch FOREX.com open positions")
        target_direction = "buy" if side == "long" else "sell"
        lots: list[dict[str, Any]] = []
        for lot in response.json().get("OpenPositions", []):
            market_id = str(lot.get("MarketId", ""))
            canonical = self._instrument_by_market_id.get(market_id, market_id)
            direction = str(lot.get("Direction", "")).lower()
            if canonical == canonical_instrument and direction == target_direction:
                lots.append(lot)
        return sorted(
            lots,
            key=lambda item: self._parse_dt(item.get("LastChangedDateTimeUtc"))
            or datetime.min.replace(tzinfo=timezone.utc),
        )

    @staticmethod
    def _add_if_done(
        payload: dict[str, Any],
        *,
        close_side: str,
        qty: float,
        stop_price: float | None,
        target_price: float | None,
    ) -> None:
        if_done: list[dict[str, Any]] = []
        if stop_price is not None:
            if_done.append(
                {
                    "OrderId": 0,
                    "Direction": close_side,
                    "Quantity": qty,
                    "TriggerPrice": stop_price,
                    "OrderType": "stop",
                }
            )
        if target_price is not None:
            if_done.append(
                {
                    "OrderId": 0,
                    "Direction": close_side,
                    "Quantity": qty,
                    "TriggerPrice": target_price,
                    "OrderType": "limit",
                }
            )
        if if_done:
            payload["IfDone"] = if_done

    @staticmethod
    def _response_accepted(payload: dict[str, Any]) -> bool:
        if int(payload.get("Status") or 0) == 1:
            return True
        return any(action.get("Status") == 1 for action in payload.get("Actions", []))

    def _cache_and_return(
        self,
        *,
        canonical_instrument: str,
        side: str,
        qty: float,
        order_type: str,
        limit_price: float | None,
        strategy: str,
        stop_price: float | None,
        target_price: float | None,
        response_payload: dict[str, Any],
        quote: _Quote | None,
    ) -> Order:
        order_id = str(
            response_payload.get("OrderId")
            or next(
                (
                    action.get("OrderId")
                    for action in response_payload.get("Actions", [])
                    if action.get("OrderId")
                ),
                "",
            )
            or uuid.uuid4().hex
        )
        status_code = int(response_payload.get("Status") or 0)
        if status_code == 1:  # Accepted
            order_status = OrderStatus.FILLED if order_type == "market" else OrderStatus.OPEN
        elif status_code == 2:  # Rejected
            order_status = OrderStatus.REJECTED
        elif status_code == 6:  # Pending
            order_status = OrderStatus.PENDING
        else:
            order_status = OrderStatus.PENDING

        fill_price = None
        fill_time = None
        if order_status == OrderStatus.FILLED and quote is not None:
            fill_price = quote.offer if side == "buy" else quote.bid
            fill_time = datetime.now(tz=timezone.utc)
        elif order_status == OrderStatus.FILLED:
            fill_price = float(response_payload.get("Price") or 0.0) or None
            fill_time = datetime.now(tz=timezone.utc)

        order = Order(
            order_id=order_id,
            instrument=canonical_instrument,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            status=order_status,
            fill_price=fill_price,
            fill_time=fill_time,
            strategy=strategy,
            stop_price=stop_price,
            target_price=target_price,
        )
        self._orders_cache[order_id] = order
        return order

    def _order_from_payload(
        self,
        payload: dict[str, Any],
        *,
        fallback: Order | None,
    ) -> Order:
        order_id = str(payload.get("OrderId") or (fallback.order_id if fallback else ""))
        market_id = str(payload.get("MarketId") or "")
        canonical = self._instrument_by_market_id.get(
            market_id, fallback.instrument if fallback else market_id
        )
        direction = str(payload.get("Direction") or "").lower()
        side = direction if direction in {"buy", "sell"} else (fallback.side if fallback else "buy")
        status_id = int(payload.get("Status") or 0)
        status_map = {
            1: OrderStatus.PENDING,
            2: OrderStatus.OPEN,
            3: OrderStatus.FILLED,
            4: OrderStatus.CANCELLED,
            5: OrderStatus.REJECTED,
        }
        status = status_map.get(status_id, fallback.status if fallback else OrderStatus.OPEN)
        return Order(
            order_id=order_id,
            instrument=canonical,
            side=side,
            qty=float(payload.get("Quantity") or (fallback.qty if fallback else 0.0)),
            order_type=(fallback.order_type if fallback else "market"),
            limit_price=(
                float(payload["TriggerPrice"])
                if payload.get("TriggerPrice") is not None
                else (fallback.limit_price if fallback else None)
            ),
            status=status,
            fill_price=(
                float(payload["Price"])
                if payload.get("Price") is not None
                else (fallback.fill_price if fallback else None)
            ),
            fill_time=self._parse_dt(payload.get("LastChangedDateTimeUtc"))
            or (fallback.fill_time if fallback else None),
            strategy=(fallback.strategy if fallback else ""),
            stop_price=(fallback.stop_price if fallback else None),
            target_price=(fallback.target_price if fallback else None),
        )

    def _fetch_account_metadata(self) -> dict[str, Any]:
        response = self._client.get(
            "/useraccount/ClientAndTradingAccount",
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, "fetch FOREX.com account metadata")
        payload = response.json()
        trading_accounts = payload.get("TradingAccounts", [])
        if not trading_accounts:
            raise ForexcomExchangeError("FOREX.com account has no trading accounts")
        return {
            "ClientAccountId": payload.get("ClientAccountId"),
            "TradingAccountId": trading_accounts[0].get("TradingAccountId"),
        }

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, str) and value.startswith("/Date("):
            ms = ForexcomExchange._extract_date_ms(value)
            if ms is None:
                return None
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _extract_date_ms(value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        start = value.find("(")
        end = value.find(")")
        if start == -1 or end == -1 or end <= start:
            return None
        body = value[start + 1 : end]
        for sep in ("+", "-"):
            idx = body.find(sep, 1)
            if idx > 0:
                body = body[:idx]
                break
        try:
            return int(body)
        except ValueError:
            return None
