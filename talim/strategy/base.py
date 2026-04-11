"""Base strategy abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal


class BaseStrategy(ABC):
    """Abstract base for all Talim strategies.

    The same on_bar implementation runs in both live and backtest modes.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier (e.g. 'momentum-ES')."""
        ...

    @abstractmethod
    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        """Process a new bar. Return a Signal if entry/exit criteria are met."""
        ...

    def load_params(self, params: dict) -> None:
        """Load or update strategy parameters at runtime."""
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def reset(self) -> None:
        """Reset internal state (e.g. between backtest runs)."""
        pass
