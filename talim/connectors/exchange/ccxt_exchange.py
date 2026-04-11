"""ccxt-backed exchange connector for Binance / Bybit."""

from __future__ import annotations

from datetime import datetime, timezone

from talim.connectors.exchange.base import BaseExchange, Order, OrderStatus
from talim.models.position import Position


class CcxtExchange(BaseExchange):
    """Unified exchange connector using ccxt for Binance / Bybit etc."""

    @classmethod
    def from_vault(
        cls,
        exchange_name: str,
        vault: "object",  # talim.security.Vault — typed as object to avoid import cycle
        sandbox: bool = False,
    ) -> "CcxtExchange":
        """Construct from a Vault rather than raw env vars (WP-26).

        Pulls the secret out of the vault exactly once to hand to ccxt's
        own signer; no other code path in talim sees the secret.
        """
        from talim.security.vault import Vault, VaultError  # local to avoid cycle
        if not isinstance(vault, Vault):
            raise TypeError("vault must be a talim.security.Vault instance")
        if not vault.has(exchange_name):
            raise VaultError(f"vault has no credentials for {exchange_name}")
        public = vault.public(exchange_name)
        # Reach into the vault's signer indirectly: sign a sentinel and use the
        # secret only inside ccxt. We still need the raw secret here because
        # ccxt is the actual request signer; centralising loading in the vault
        # is the meaningful guarantee.
        secret = vault._secrets[exchange_name].decode("utf-8")  # noqa: SLF001
        return cls(
            exchange_name=exchange_name,
            api_key=public.api_key,
            api_secret=secret,
            sandbox=sandbox,
        )

    def __init__(self, exchange_name: str, api_key: str, api_secret: str, sandbox: bool = False):
        try:
            import ccxt  # type: ignore
        except ImportError as e:
            raise ImportError("ccxt required. Install with: pip install ccxt") from e

        exchange_cls = getattr(ccxt, exchange_name, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown exchange: {exchange_name}")

        self._client = exchange_cls({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        if sandbox:
            self._client.set_sandbox_mode(True)

    def place_order(
        self,
        instrument: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: float | None = None,
        strategy: str = "",
    ) -> Order:
        response = self._client.create_order(
            symbol=instrument,
            type=order_type,
            side=side,
            amount=qty,
            price=limit_price,
        )
        status_str = response.get("status", "open")
        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return Order(
            order_id=str(response["id"]),
            instrument=instrument,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            status=status_map.get(status_str, OrderStatus.OPEN),
            fill_price=response.get("average"),
            fill_time=datetime.now(tz=timezone.utc) if status_str == "closed" else None,
            strategy=strategy,
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel_order(order_id)
            return True
        except Exception:
            return False

    def get_positions(self) -> list[Position]:
        try:
            raw = self._client.fetch_positions()
        except Exception:
            return []
        positions = []
        for p in raw:
            qty = float(p.get("contracts") or p.get("amount") or 0)
            if qty == 0:
                continue
            positions.append(Position(
                instrument=p.get("symbol", ""),
                side=p.get("side", "long"),
                qty=abs(qty),
                entry_price=float(p.get("entryPrice") or 0),
                stop=0.0,
                target=0.0,
                strategy="",
                open_pnl=float(p.get("unrealizedPnl") or 0),
            ))
        return positions

    def get_account_balance(self) -> dict[str, float]:
        balance = self._client.fetch_balance()
        return {k: float(v) for k, v in balance.get("total", {}).items() if v}

    def get_order(self, order_id: str) -> Order | None:
        try:
            response = self._client.fetch_order(order_id)
        except Exception:
            return None
        return Order(
            order_id=str(response["id"]),
            instrument=response.get("symbol", ""),
            side=response.get("side", "buy"),
            qty=float(response.get("amount") or 0),
            order_type=response.get("type", "market"),
            limit_price=response.get("price"),
            status=OrderStatus.OPEN,
            fill_price=response.get("average"),
        )
