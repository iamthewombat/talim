"""Canonical CFD venue contract models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
VALID_POSITION_MODELS = {"netted", "hedged", "unknown"}


def _normalise_day(value: str) -> str:
    day = value.strip().upper()
    if day not in VALID_WEEKDAYS:
        raise ValueError(f"invalid weekday {value!r}; must be one of {sorted(VALID_WEEKDAYS)}")
    return day


def _normalise_time(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid time {value!r}; expected HH:MM")
    hour, minute = parts
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError(f"invalid time {value!r}; expected HH:MM")
    h = int(hour)
    m = int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"invalid time {value!r}; expected HH:MM")
    return f"{h:02d}:{m:02d}"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A weekly trading window in the market's local timezone."""

    opens_day: str
    opens_time: str
    closes_day: str
    closes_time: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "opens_day", _normalise_day(self.opens_day))
        object.__setattr__(self, "closes_day", _normalise_day(self.closes_day))
        object.__setattr__(self, "opens_time", _normalise_time(self.opens_time))
        object.__setattr__(self, "closes_time", _normalise_time(self.closes_time))

    def to_dict(self) -> dict[str, str]:
        return {
            "opens_day": self.opens_day,
            "opens_time": self.opens_time,
            "closes_day": self.closes_day,
            "closes_time": self.closes_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "SessionWindow":
        return cls(
            opens_day=data["opens_day"],
            opens_time=data["opens_time"],
            closes_day=data["closes_day"],
            closes_time=data["closes_time"],
        )


@dataclass(frozen=True, slots=True)
class MarketSession:
    """Session metadata for a canonical instrument."""

    timezone: str
    windows: tuple[SessionWindow, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "windows": [window.to_dict() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketSession":
        windows = tuple(SessionWindow.from_dict(item) for item in data.get("windows", []))
        return cls(timezone=data["timezone"], windows=windows)


@dataclass(frozen=True, slots=True)
class VenueCapabilities:
    """Order and data semantics supported by a broker venue."""

    venue: str
    supports_market_orders: bool = True
    supports_marketable_limits: bool = False
    supports_limit_orders: bool = True
    supports_stop_orders: bool = True
    supports_attached_stops_limits: bool = True
    supports_guaranteed_stops: bool = False
    supports_partial_fills: bool = True
    supports_working_orders: bool = True
    supports_streaming_prices: bool = True
    supports_demo: bool = True
    supports_live: bool = True
    position_model: str = "unknown"

    def __post_init__(self) -> None:
        model = self.position_model.lower()
        if model not in VALID_POSITION_MODELS:
            raise ValueError(
                f"invalid position model {self.position_model!r}; must be one of "
                f"{sorted(VALID_POSITION_MODELS)}"
            )
        object.__setattr__(self, "position_model", model)

    def validate_order(
        self,
        *,
        order_type: str,
        attached_stop: bool = False,
        attached_limit: bool = False,
        guaranteed_stop: bool = False,
        working_order: bool = False,
    ) -> None:
        """Fail fast on order semantics the venue cannot support."""

        normalised = order_type.strip().lower()
        if normalised == "market" and not self.supports_market_orders:
            raise ValueError(f"{self.venue} does not support market orders")
        if normalised == "marketable_limit" and not self.supports_marketable_limits:
            raise ValueError(f"{self.venue} does not support marketable limit orders")
        if normalised == "limit" and not self.supports_limit_orders:
            raise ValueError(f"{self.venue} does not support limit orders")
        if normalised == "stop" and not self.supports_stop_orders:
            raise ValueError(f"{self.venue} does not support stop orders")
        if (attached_stop or attached_limit) and not self.supports_attached_stops_limits:
            raise ValueError(f"{self.venue} does not support attached stop/limit parameters")
        if guaranteed_stop and not self.supports_guaranteed_stops:
            raise ValueError(f"{self.venue} does not support guaranteed stops")
        if working_order and not self.supports_working_orders:
            raise ValueError(f"{self.venue} does not support working orders")

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "supports_market_orders": self.supports_market_orders,
            "supports_marketable_limits": self.supports_marketable_limits,
            "supports_limit_orders": self.supports_limit_orders,
            "supports_stop_orders": self.supports_stop_orders,
            "supports_attached_stops_limits": self.supports_attached_stops_limits,
            "supports_guaranteed_stops": self.supports_guaranteed_stops,
            "supports_partial_fills": self.supports_partial_fills,
            "supports_working_orders": self.supports_working_orders,
            "supports_streaming_prices": self.supports_streaming_prices,
            "supports_demo": self.supports_demo,
            "supports_live": self.supports_live,
            "position_model": self.position_model,
        }

    @classmethod
    def from_dict(cls, venue: str, data: dict[str, Any]) -> "VenueCapabilities":
        return cls(venue=venue, **data)


@dataclass(frozen=True, slots=True)
class VenueInstrumentMapping:
    """Venue-specific identifiers for a canonical CFD instrument."""

    venue: str
    lookup_hint: str
    broker_symbol: str | None = None
    market_id: str | None = None
    expiry: str | None = None
    venue_display_name: str | None = None
    product_type: str | None = None
    notes: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.broker_symbol)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookup_hint": self.lookup_hint,
            "broker_symbol": self.broker_symbol,
            "market_id": self.market_id,
            "expiry": self.expiry,
            "venue_display_name": self.venue_display_name,
            "product_type": self.product_type,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, venue: str, data: dict[str, Any]) -> "VenueInstrumentMapping":
        return cls(
            venue=venue,
            lookup_hint=data["lookup_hint"],
            broker_symbol=data.get("broker_symbol"),
            market_id=data.get("market_id"),
            expiry=data.get("expiry"),
            venue_display_name=data.get("venue_display_name"),
            product_type=data.get("product_type"),
            notes=data.get("notes", ""),
        )


def _default_market_session() -> MarketSession:
    return MarketSession(timezone="UTC", windows=())


@dataclass(frozen=True, slots=True)
class CfdInstrumentSpec:
    """Canonical CFD instrument definition shared by all venues."""

    canonical_id: str
    display_name: str
    asset_class: str
    quote_currency: str
    tick_size: float | None = None
    price_precision: int | None = None
    min_size: float | None = None
    size_step: float | None = None
    point_value: float | None = None
    margin_rate: float | None = None
    financing_model: str = ""
    session: MarketSession = field(default_factory=_default_market_session)
    venues: tuple[VenueInstrumentMapping, ...] = ()

    def __post_init__(self) -> None:
        if "." not in self.canonical_id:
            raise ValueError(
                f"invalid canonical instrument id {self.canonical_id!r}; "
                "expected a dotted form such as 'AU200.cash'"
            )

    @property
    def venue_names(self) -> tuple[str, ...]:
        return tuple(mapping.venue for mapping in self.venues)

    def venue_mapping(self, venue: str) -> VenueInstrumentMapping:
        for mapping in self.venues:
            if mapping.venue == venue:
                return mapping
        raise KeyError(f"{self.canonical_id} has no mapping for venue {venue!r}")

    def missing_trade_fields(self) -> tuple[str, ...]:
        required = {
            "tick_size": self.tick_size,
            "price_precision": self.price_precision,
            "min_size": self.min_size,
            "size_step": self.size_step,
            "point_value": self.point_value,
            "margin_rate": self.margin_rate,
        }
        return tuple(name for name, value in required.items() if value is None)

    def is_trade_ready(self, venue: str) -> bool:
        mapping = self.venue_mapping(venue)
        return not self.missing_trade_fields() and mapping.is_resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "display_name": self.display_name,
            "asset_class": self.asset_class,
            "quote_currency": self.quote_currency,
            "tick_size": self.tick_size,
            "price_precision": self.price_precision,
            "min_size": self.min_size,
            "size_step": self.size_step,
            "point_value": self.point_value,
            "margin_rate": self.margin_rate,
            "financing_model": self.financing_model,
            "session": self.session.to_dict(),
            "venues": {mapping.venue: mapping.to_dict() for mapping in self.venues},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CfdInstrumentSpec":
        venues = tuple(
            VenueInstrumentMapping.from_dict(venue, mapping)
            for venue, mapping in data.get("venues", {}).items()
        )
        return cls(
            canonical_id=data["canonical_id"],
            display_name=data["display_name"],
            asset_class=data["asset_class"],
            quote_currency=data["quote_currency"],
            tick_size=data.get("tick_size"),
            price_precision=data.get("price_precision"),
            min_size=data.get("min_size"),
            size_step=data.get("size_step"),
            point_value=data.get("point_value"),
            margin_rate=data.get("margin_rate"),
            financing_model=data.get("financing_model", ""),
            session=MarketSession.from_dict(data["session"]),
            venues=venues,
        )
