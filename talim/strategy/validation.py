"""Strategy-specific pending signal validation (WP-77).

Validation answers: "is this old HITL signal still actionable now?" It is
advisory in WP-77 and becomes approval-enforcing in WP-78.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal

ValidationStatus = Literal[
    "valid",
    "stale",
    "price_moved_too_far",
    "condition_invalidated",
    "risk_changed",
    "data_unavailable",
]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    approval_allowed: bool
    reason: str
    current_price: float | None = None
    movement_r: float | None = None
    movement_atr: float | None = None
    bars_since_signal: int | None = None
    evaluated_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _signal_time(signal: Signal) -> datetime | None:
    ts = signal.timestamp
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def bars_since_signal(signal: Signal, bars: list[OHLCVBar]) -> int | None:
    ts = _signal_time(signal)
    if ts is None:
        return None
    count = 0
    for bar in bars:
        bts = bar.timestamp
        if bts.tzinfo is None:
            bts = bts.replace(tzinfo=timezone.utc)
        if bts > ts:
            count += 1
    return count


def movement_r(signal: Signal, current_price: float) -> float | None:
    risk = abs(signal.entry_price - signal.stop)
    if risk <= 0:
        return None
    signed = current_price - signal.entry_price
    if signal.side.lower() == "short":
        signed = -signed
    return signed / risk


def default_validate_signal(
    signal: Signal,
    bars: list[OHLCVBar],
    *,
    max_bars_since_signal: int = 3,
    max_adverse_r: float = 0.25,
    max_favourable_r: float = 0.75,
    atr: float | None = None,
) -> ValidationResult:
    """Conservative default validity check for strategies without overrides."""
    if not bars:
        return ValidationResult(
            status="data_unavailable",
            approval_allowed=False,
            reason="no recent bars available for validation",
            evaluated_at=_now_iso(),
        )
    latest = bars[-1]
    if latest.instrument != signal.instrument:
        return ValidationResult(
            status="data_unavailable",
            approval_allowed=False,
            reason=f"latest bars are for {latest.instrument}, not {signal.instrument}",
            current_price=latest.close,
            evaluated_at=_now_iso(),
        )

    bss = bars_since_signal(signal, bars)
    move_r = movement_r(signal, latest.close)
    move_atr = None
    if atr and atr > 0:
        signed = latest.close - signal.entry_price
        if signal.side.lower() == "short":
            signed = -signed
        move_atr = signed / atr

    if bss is not None and bss > max_bars_since_signal:
        return ValidationResult(
            status="stale",
            approval_allowed=False,
            reason=f"signal is {bss} bars old; maximum is {max_bars_since_signal}",
            current_price=latest.close,
            movement_r=move_r,
            movement_atr=move_atr,
            bars_since_signal=bss,
            evaluated_at=_now_iso(),
        )
    if move_r is not None and move_r < -max_adverse_r:
        return ValidationResult(
            status="price_moved_too_far",
            approval_allowed=False,
            reason=f"price moved adversely by {move_r:.2f}R; limit is -{max_adverse_r:.2f}R",
            current_price=latest.close,
            movement_r=move_r,
            movement_atr=move_atr,
            bars_since_signal=bss,
            evaluated_at=_now_iso(),
        )
    if move_r is not None and move_r > max_favourable_r:
        return ValidationResult(
            status="price_moved_too_far",
            approval_allowed=False,
            reason=f"price already moved {move_r:.2f}R toward target; limit is {max_favourable_r:.2f}R",
            current_price=latest.close,
            movement_r=move_r,
            movement_atr=move_atr,
            bars_since_signal=bss,
            evaluated_at=_now_iso(),
        )

    return ValidationResult(
        status="valid",
        approval_allowed=True,
        reason="signal remains within default age and price-movement limits",
        current_price=latest.close,
        movement_r=move_r,
        movement_atr=move_atr,
        bars_since_signal=bss,
        evaluated_at=_now_iso(),
    )
