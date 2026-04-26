"""Simple moving average."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Vectorised SMA. Returns ``None`` for the first ``period - 1`` positions."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = []
    running = 0.0
    window: list[float] = []
    for v in values:
        window.append(float(v))
        running += float(v)
        if len(window) > period:
            running -= window[-period - 1]
        if len(window) >= period:
            out.append(running / period if len(window) == period else running / period)
        else:
            out.append(None)
    return out


class SmaStream:
    """Streaming SMA. Returns ``None`` until ``period`` values have been seen."""

    __slots__ = ("period", "_window", "_running")

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._window: deque[float] = deque(maxlen=period)
        self._running = 0.0

    @property
    def value(self) -> float | None:
        if len(self._window) < self.period:
            return None
        return self._running / self.period

    def update(self, value: float) -> float | None:
        if len(self._window) == self.period:
            self._running -= self._window[0]
        self._window.append(float(value))
        self._running += float(value)
        return self.value

    def reset(self) -> None:
        self._window.clear()
        self._running = 0.0
