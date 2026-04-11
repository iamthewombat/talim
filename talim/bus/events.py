"""Event type definitions for the Redis event bus."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BarEvent:
    """A new OHLCV bar has been received."""
    event_type: str = "bar"
    instrument: str = ""
    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    timeframe: str = "5m"

    def to_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> BarEvent:
        return cls(
            instrument=d.get("instrument", ""),
            timestamp=d.get("timestamp", ""),
            open=float(d.get("open", 0)),
            high=float(d.get("high", 0)),
            low=float(d.get("low", 0)),
            close=float(d.get("close", 0)),
            volume=float(d.get("volume", 0)),
            timeframe=d.get("timeframe", "5m"),
        )


@dataclass(frozen=True, slots=True)
class RegimeChangeEvent:
    """The detected market regime has changed."""
    event_type: str = "regime_change"
    instrument: str = ""
    old_regime: str = ""
    new_regime: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> RegimeChangeEvent:
        return cls(
            instrument=d.get("instrument", ""),
            old_regime=d.get("old_regime", ""),
            new_regime=d.get("new_regime", ""),
            timestamp=d.get("timestamp", ""),
        )


@dataclass(frozen=True, slots=True)
class SignalEvent:
    """A trade signal has been generated."""
    event_type: str = "signal"
    instrument: str = ""
    strategy: str = ""
    side: str = ""
    entry_price: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    rationale: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> SignalEvent:
        return cls(
            instrument=d.get("instrument", ""),
            strategy=d.get("strategy", ""),
            side=d.get("side", ""),
            entry_price=float(d.get("entry_price", 0)),
            stop=float(d.get("stop", 0)),
            target=float(d.get("target", 0)),
            rationale=d.get("rationale", ""),
            timestamp=d.get("timestamp", ""),
        )


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """A trade has been executed."""
    event_type: str = "trade"
    instrument: str = ""
    strategy: str = ""
    side: str = ""
    qty: float = 0.0
    fill_price: float = 0.0
    order_type: str = "market"
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> TradeEvent:
        return cls(
            instrument=d.get("instrument", ""),
            strategy=d.get("strategy", ""),
            side=d.get("side", ""),
            qty=float(d.get("qty", 0)),
            fill_price=float(d.get("fill_price", 0)),
            order_type=d.get("order_type", "market"),
            timestamp=d.get("timestamp", ""),
        )


# Registry for deserialisation
EVENT_TYPES: dict[str, type] = {
    "bar": BarEvent,
    "regime_change": RegimeChangeEvent,
    "signal": SignalEvent,
    "trade": TradeEvent,
}


def deserialize_event(data: dict[str, str]) -> BarEvent | RegimeChangeEvent | SignalEvent | TradeEvent:
    """Deserialize a dict from Redis into the appropriate event type."""
    event_type = data.get("event_type", "")
    cls = EVENT_TYPES.get(event_type)
    if cls is None:
        raise ValueError(f"Unknown event type: {event_type}")
    return cls.from_dict(data)
