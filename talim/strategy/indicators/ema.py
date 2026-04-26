"""Exponential moving average."""

from __future__ import annotations

from collections.abc import Sequence


def ema(values: Sequence[float], period: int) -> list[float]:
    """Vectorised EMA over ``values`` using the 2/(period+1) smoothing factor.

    The first value seeds the EMA (no warm-up NaNs). This matches the
    streaming form, where the first observation initialises the state.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []
    k = 2.0 / (period + 1)
    out: list[float] = [float(values[0])]
    for v in values[1:]:
        out.append(float(v) * k + out[-1] * (1 - k))
    return out


class EmaStream:
    """Streaming EMA. First ``update`` returns that value; subsequent updates smooth."""

    __slots__ = ("period", "_k", "_value")

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._k = 2.0 / (period + 1)
        self._value: float | None = None

    @property
    def value(self) -> float | None:
        return self._value

    def update(self, value: float) -> float:
        if self._value is None:
            self._value = float(value)
        else:
            self._value = float(value) * self._k + self._value * (1 - self._k)
        return self._value

    def reset(self) -> None:
        self._value = None
