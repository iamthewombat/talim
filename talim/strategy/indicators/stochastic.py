"""Stochastic oscillator (%K / %D).

Classic Lane stochastic:
    %K = 100 * (close - lowest_low(n)) / (highest_high(n) - lowest_low(n))
    %D = simple MA of %K over ``d_period`` bars

Returns ``None`` until ``k_period`` highs/lows and ``d_period`` %K values
have been observed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class StochasticValue:
    k: float
    d: float | None


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> list[StochasticValue | None]:
    """Vectorised stochastic. Returns ``None`` for warm-up positions."""
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs, lows, closes must be the same length")
    out: list[StochasticValue | None] = []
    k_values: list[float] = []
    for i in range(n):
        if i + 1 < k_period:
            out.append(None)
            k_values.append(float("nan"))
            continue
        window_hi = max(float(h) for h in highs[i + 1 - k_period : i + 1])
        window_lo = min(float(lo) for lo in lows[i + 1 - k_period : i + 1])
        denom = window_hi - window_lo
        k = 50.0 if denom == 0 else 100.0 * (float(closes[i]) - window_lo) / denom
        k_values.append(k)
        recent_ks = [v for v in k_values[i + 1 - d_period : i + 1] if v == v]
        if len(recent_ks) < d_period:
            out.append(StochasticValue(k=k, d=None))
        else:
            out.append(StochasticValue(k=k, d=sum(recent_ks) / d_period))
    return out


class StochasticStream:
    """Streaming stochastic."""

    __slots__ = ("k_period", "d_period", "_highs", "_lows", "_ks")

    def __init__(self, k_period: int = 14, d_period: int = 3) -> None:
        if k_period <= 0 or d_period <= 0:
            raise ValueError("periods must be positive")
        self.k_period = k_period
        self.d_period = d_period
        self._highs: deque[float] = deque(maxlen=k_period)
        self._lows: deque[float] = deque(maxlen=k_period)
        self._ks: deque[float] = deque(maxlen=d_period)

    def update(self, high: float, low: float, close: float) -> StochasticValue | None:
        self._highs.append(float(high))
        self._lows.append(float(low))
        if len(self._highs) < self.k_period:
            return None
        window_hi = max(self._highs)
        window_lo = min(self._lows)
        denom = window_hi - window_lo
        k = 50.0 if denom == 0 else 100.0 * (float(close) - window_lo) / denom
        self._ks.append(k)
        if len(self._ks) < self.d_period:
            return StochasticValue(k=k, d=None)
        return StochasticValue(k=k, d=sum(self._ks) / self.d_period)

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._ks.clear()
