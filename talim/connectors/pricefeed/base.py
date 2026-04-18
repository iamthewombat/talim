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

    def prime_history(self, instrument: str, min_bars: int = 50) -> list[OHLCVBar]:
        """Optionally backfill historical bars and emit them to callbacks.

        Live feeds can override this to populate scanner history on demand.
        Mocks and scaffolds can safely inherit the default no-op.
        """
        return []

    def poll_once(self, instrument: str) -> OHLCVBar | None:
        """Optionally fetch and emit the newest completed bar for one instrument.

        Live feeds can override this to support cron-style polling. The default
        implementation is a no-op so existing feeds remain valid.
        """
        return None

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def subscribe(self, instrument: str) -> None:
        ...
