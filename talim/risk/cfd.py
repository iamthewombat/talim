"""CFD-specific risk, session, and financing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from talim.cfd import CfdInstrumentRegistry, CfdInstrumentSpec, CfdRegistryError, MarketSession, load_default_registry
from talim.models.position import Position

DEFAULT_CFD_FINANCING_ANNUAL_RATE = 0.08

_DAY_INDEX = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}
_MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    """Exposure and margin numbers for a CFD trade or position."""

    notional: float
    required_margin: float
    quote_currency: str


@lru_cache(maxsize=1)
def _cached_default_registry() -> CfdInstrumentRegistry:
    return load_default_registry()


def _registry_or_default(registry: CfdInstrumentRegistry | None = None) -> CfdInstrumentRegistry:
    return registry or _cached_default_registry()


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _window_offset(day: str, clock_time: str) -> int:
    hour, minute = (int(part) for part in clock_time.split(":"))
    return (_DAY_INDEX[day] * _MINUTES_PER_DAY) + (hour * 60) + minute


def resolve_cfd_spec(
    instrument: str,
    registry: CfdInstrumentRegistry | None = None,
) -> CfdInstrumentSpec | None:
    try:
        return _registry_or_default(registry).get(instrument)
    except CfdRegistryError:
        return None


def is_cfd_instrument(
    instrument: str,
    registry: CfdInstrumentRegistry | None = None,
) -> bool:
    return resolve_cfd_spec(instrument, registry=registry) is not None


def cfd_family(
    instrument: str,
    registry: CfdInstrumentRegistry | None = None,
) -> str | None:
    spec = resolve_cfd_spec(instrument, registry=registry)
    if spec is None:
        return None
    return spec.canonical_id.split(".", 1)[0]


def same_cfd_family(
    left: str,
    right: str,
    registry: CfdInstrumentRegistry | None = None,
) -> bool:
    left_family = cfd_family(left, registry=registry)
    if left_family is None:
        return False
    return left_family == cfd_family(right, registry=registry)


def exposure_for_trade(
    instrument: str,
    *,
    qty: float,
    price: float,
    registry: CfdInstrumentRegistry | None = None,
) -> ExposureSnapshot | None:
    spec = resolve_cfd_spec(instrument, registry=registry)
    if spec is None:
        return None
    point_value = spec.point_value or 1.0
    notional = abs(qty * price * point_value)
    margin_rate = spec.margin_rate or 0.0
    return ExposureSnapshot(
        notional=notional,
        required_margin=notional * margin_rate,
        quote_currency=spec.quote_currency,
    )


def exposure_for_position(
    position: Position,
    registry: CfdInstrumentRegistry | None = None,
) -> ExposureSnapshot | None:
    return exposure_for_trade(
        position.instrument,
        qty=position.qty,
        price=position.entry_price,
        registry=registry,
    )


def is_session_open(session: MarketSession, *, at: datetime | None = None) -> bool:
    """Return True when the given timestamp falls inside any configured window."""
    if not session.windows:
        return True

    current = _coerce_datetime(at).astimezone(ZoneInfo(session.timezone))
    current_offset = (
        current.weekday() * _MINUTES_PER_DAY
        + current.hour * 60
        + current.minute
    )

    for window in session.windows:
        start = _window_offset(window.opens_day, window.opens_time)
        end = _window_offset(window.closes_day, window.closes_time)
        if start == end:
            return True
        if start < end and start <= current_offset < end:
            return True
        if start > end and (current_offset >= start or current_offset < end):
            return True

    return False


def is_instrument_tradeable(
    instrument: str,
    *,
    at: datetime | None = None,
    registry: CfdInstrumentRegistry | None = None,
) -> bool:
    spec = resolve_cfd_spec(instrument, registry=registry)
    if spec is None:
        return True
    return is_session_open(spec.session, at=at)


def estimate_financing_cost(
    position: Position,
    *,
    annual_rate: float = DEFAULT_CFD_FINANCING_ANNUAL_RATE,
    at: datetime | None = None,
    registry: CfdInstrumentRegistry | None = None,
) -> float:
    """Estimate accrued financing for overnight cash CFDs."""
    spec = resolve_cfd_spec(position.instrument, registry=registry)
    if spec is None or spec.financing_model != "overnight_cash_cfd":
        return 0.0
    if position.entry_time is None or annual_rate <= 0:
        return 0.0

    current = _coerce_datetime(at)
    entry = _coerce_datetime(position.entry_time)
    if current <= entry:
        return 0.0

    local_tz = ZoneInfo(spec.session.timezone)
    days_held = (current.astimezone(local_tz).date() - entry.astimezone(local_tz).date()).days
    if days_held <= 0:
        return 0.0

    point_value = spec.point_value or 1.0
    notional = abs(position.qty * position.entry_price * point_value)
    return notional * annual_rate / 365.0 * days_held


def select_account_balance(
    balances: dict[str, float],
    positions: list[Position] | None = None,
    *,
    registry: CfdInstrumentRegistry | None = None,
) -> tuple[str, float]:
    """Choose the most relevant account balance from a broker response."""
    numeric_balances = {
        currency: float(value)
        for currency, value in balances.items()
        if isinstance(value, (int, float))
    }
    if not numeric_balances:
        return "", 0.0
    if len(numeric_balances) == 1:
        currency, amount = next(iter(numeric_balances.items()))
        return currency, amount

    preferred_currencies = {
        spec.quote_currency
        for position in (positions or [])
        if (spec := resolve_cfd_spec(position.instrument, registry=registry)) is not None
    }
    if len(preferred_currencies) == 1:
        preferred = next(iter(preferred_currencies))
        if preferred in numeric_balances:
            return preferred, numeric_balances[preferred]

    currency, amount = max(numeric_balances.items(), key=lambda item: abs(item[1]))
    return currency, amount
