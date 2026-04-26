"""Donchian channel — highest high / lowest low over a lookback window."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DonchianChannel:
    upper: float
    lower: float
    middle: float


def donchian(
    highs: Sequence[float],
    lows: Sequence[float],
    period: int = 20,
) -> list[DonchianChannel | None]:
    """Vectorised Donchian channel. Returns ``None`` for warm-up positions."""
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(highs)
    if len(lows) != n:
        raise ValueError("highs and lows must be the same length")
    out: list[DonchianChannel | None] = []
    for i in range(n):
        if i + 1 < period:
            out.append(None)
            continue
        upper = max(float(h) for h in highs[i + 1 - period : i + 1])
        lower = min(float(lo) for lo in lows[i + 1 - period : i + 1])
        out.append(DonchianChannel(upper=upper, lower=lower, middle=(upper + lower) / 2))
    return out


class DonchianStream:
    """Streaming Donchian channel."""

    __slots__ = ("period", "_highs", "_lows")

    def __init__(self, period: int = 20) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)

    def update(self, high: float, low: float) -> DonchianChannel | None:
        self._highs.append(float(high))
        self._lows.append(float(low))
        if len(self._highs) < self.period:
            return None
        upper = max(self._highs)
        lower = min(self._lows)
        return DonchianChannel(upper=upper, lower=lower, middle=(upper + lower) / 2)

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
