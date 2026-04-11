"""Base price feed abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from talim.models.bar import OHLCVBar

BarCallback = Callable[[OHLCVBar], None]


class BasePriceFeed(ABC):
    """Abstract base for all price feed connectors."""

    def __init__(self) -> None:
        self._callbacks: list[BarCallback] = []
        self._subscribed: set[str] = set()
        self._connected: bool = False

    def on_bar(self, callback: BarCallback) -> None:
        """Register a callback to be invoked on every bar."""
        self._callbacks.append(callback)

    def _emit(self, bar: OHLCVBar) -> None:
        for cb in self._callbacks:
            cb(bar)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscriptions(self) -> set[str]:
        return set(self._subscribed)

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def subscribe(self, instrument: str) -> None:
        ...
