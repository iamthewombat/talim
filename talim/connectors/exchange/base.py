"""Base exchange abstract class and order types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from talim.models.position import Position


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents an order placed on an exchange."""

    order_id: str
    instrument: str
    side: str  # "buy" or "sell"
    qty: float
    order_type: str = "market"  # "market" or "limit"
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    fill_time: datetime | None = None
    strategy: str = ""


class BaseExchange(ABC):
    """Abstract base for all exchange connectors."""

    @abstractmethod
    def place_order(
        self,
        instrument: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: float | None = None,
        strategy: str = "",
    ) -> Order:
        """Submit an order to the exchange. Returns the Order object."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order. Returns True if cancelled."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return current open positions."""
        ...

    @abstractmethod
    def get_account_balance(self) -> dict[str, float]:
        """Return balance per currency/asset."""
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None:
        """Look up an order by id."""
        ...
