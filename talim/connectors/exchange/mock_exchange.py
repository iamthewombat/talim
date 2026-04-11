"""Mock exchange — records orders in memory and simulates fills."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from talim.connectors.exchange.base import BaseExchange, Order, OrderStatus
from talim.models.position import Position


class MockExchange(BaseExchange):
    """In-memory exchange for testing. Simulates instant market fills."""

    def __init__(self, starting_balance: float = 100000.0, fill_price_map: dict[str, float] | None = None):
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}  # keyed by instrument
        self._balance: dict[str, float] = {"USD": starting_balance}
        # Optional price map for deterministic fills
        self._fill_prices: dict[str, float] = fill_price_map or {}

    def set_fill_price(self, instrument: str, price: float) -> None:
        """Set the price at which market orders for this instrument will fill."""
        self._fill_prices[instrument] = price

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

        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            instrument=instrument,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            status=OrderStatus.OPEN,
            strategy=strategy,
        )

        # Market orders fill instantly
        if order_type == "market":
            fill_price = self._fill_prices.get(instrument, limit_price or 0.0)
            order.status = OrderStatus.FILLED
            order.fill_price = fill_price
            order.fill_time = datetime.now(tz=timezone.utc)
            self._apply_fill(order)

        self._orders[order_id] = order
        return order

    def _apply_fill(self, order: Order) -> None:
        """Update positions and balance based on a filled order."""
        instrument = order.instrument
        signed_qty = order.qty if order.side == "buy" else -order.qty
        fill_price = order.fill_price or 0.0

        if instrument in self._positions:
            pos = self._positions[instrument]
            current_signed = pos.qty if pos.side == "long" else -pos.qty
            new_signed = current_signed + signed_qty
            if abs(new_signed) < 1e-9:
                # Closed out
                del self._positions[instrument]
            else:
                pos.side = "long" if new_signed > 0 else "short"
                pos.qty = abs(new_signed)
                pos.entry_price = fill_price  # simplified — real exchanges do weighted avg
        else:
            self._positions[instrument] = Position(
                instrument=instrument,
                side="long" if signed_qty > 0 else "short",
                qty=abs(signed_qty),
                entry_price=fill_price,
                stop=0.0,
                target=0.0,
                strategy=order.strategy,
                entry_time=order.fill_time,
                position_id=order.order_id,
            )

        # Naive balance update — cost basis
        cost = signed_qty * fill_price
        self._balance["USD"] = self._balance.get("USD", 0.0) - cost

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None:
            return False
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        order.status = OrderStatus.CANCELLED
        return True

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_account_balance(self) -> dict[str, float]:
        return dict(self._balance)

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)
