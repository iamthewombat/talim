"""Bollinger Bands using a simple moving average and population std.

This matches the inline computation in ``mean-reversion-US500`` (population
variance, dividing by ``n`` rather than ``n - 1``). Returns ``None`` until
``period`` samples have been seen.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BollingerBands:
    middle: float
    upper: float
    lower: float


def bollinger(
    values: Sequence[float],
    period: int = 20,
    num_std: float = 2.0,
) -> list[BollingerBands | None]:
    """Vectorised Bollinger Bands. Returns ``None`` for warm-up positions."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[BollingerBands | None] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
            continue
        window = [float(v) for v in values[i + 1 - period : i + 1]]
        middle = sum(window) / period
        variance = sum((x - middle) ** 2 for x in window) / period
        std = math.sqrt(variance)
        out.append(
            BollingerBands(
                middle=middle,
                upper=middle + num_std * std,
                lower=middle - num_std * std,
            )
        )
    return out


class BollingerStream:
    """Streaming Bollinger Bands with population std."""

    __slots__ = ("period", "num_std", "_window")

    def __init__(self, period: int = 20, num_std: float = 2.0) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self.num_std = num_std
        self._window: deque[float] = deque(maxlen=period)

    @property
    def value(self) -> BollingerBands | None:
        if len(self._window) < self.period:
            return None
        window = list(self._window)
        middle = sum(window) / self.period
        variance = sum((x - middle) ** 2 for x in window) / self.period
        std = math.sqrt(variance)
        return BollingerBands(
            middle=middle,
            upper=middle + self.num_std * std,
            lower=middle - self.num_std * std,
        )

    def update(self, value: float) -> BollingerBands | None:
        self._window.append(float(value))
        return self.value

    def reset(self) -> None:
        self._window.clear()
