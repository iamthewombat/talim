"""Relative Strength Index — Wilder smoothing.

Canonical Wilder RSI. Returns values in [0, 100]. Output is ``None`` until
``period + 1`` samples have been seen (so the first period of gains/losses
can be averaged).
"""

from __future__ import annotations

from collections.abc import Sequence


def rsi_wilder(values: Sequence[float], period: int = 14) -> list[float | None]:
    """Vectorised Wilder RSI. Returns ``None`` for positions with too few samples."""
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = float(values[i]) - float(values[i - 1])
        if delta >= 0:
            gains += delta
        else:
            losses += -delta

    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        delta = float(values[i]) - float(values[i - 1])
        gain = delta if delta >= 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from_averages(avg_gain, avg_loss)

    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class RsiStream:
    """Streaming Wilder RSI. Returns ``None`` until ``period + 1`` updates."""

    __slots__ = ("period", "_prev", "_avg_gain", "_avg_loss", "_count")

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._prev: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._count = 0  # number of deltas observed

    @property
    def value(self) -> float | None:
        if self._count < self.period:
            return None
        return _rsi_from_averages(self._avg_gain, self._avg_loss)

    def update(self, value: float) -> float | None:
        if self._prev is None:
            self._prev = float(value)
            return None
        delta = float(value) - self._prev
        self._prev = float(value)
        gain = delta if delta >= 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        self._count += 1
        if self._count <= self.period:
            self._avg_gain += gain
            self._avg_loss += loss
            if self._count == self.period:
                self._avg_gain /= self.period
                self._avg_loss /= self.period
                return _rsi_from_averages(self._avg_gain, self._avg_loss)
            return None
        self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
        self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        return _rsi_from_averages(self._avg_gain, self._avg_loss)

    def reset(self) -> None:
        self._prev = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._count = 0
