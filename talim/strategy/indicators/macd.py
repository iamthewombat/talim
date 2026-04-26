"""MACD — moving average convergence/divergence.

Built from EMAs so it inherits the same 2/(period+1) smoothing semantics.
The signal line is an EMA of the MACD line. Histogram is ``macd - signal``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from talim.strategy.indicators.ema import EmaStream, ema


@dataclass(frozen=True)
class MacdValue:
    macd: float
    signal: float
    histogram: float


def macd(
    values: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[MacdValue]:
    """Vectorised MACD. The first output is produced from the first sample.

    No warm-up ``None`` values — EMAs seed from the first point, so the
    first ``MacdValue`` is effectively ``(0, 0, 0)``. Callers that want a
    warm-up window should slice accordingly.
    """
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal_line = ema(macd_line, signal_period)
    return [
        MacdValue(macd=m, signal=s, histogram=m - s)
        for m, s in zip(macd_line, signal_line)
    ]


class MacdStream:
    """Streaming MACD via three EMAs (fast, slow, signal)."""

    __slots__ = ("_fast", "_slow", "_signal")

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        self._fast = EmaStream(fast_period)
        self._slow = EmaStream(slow_period)
        self._signal = EmaStream(signal_period)

    def update(self, value: float) -> MacdValue:
        fast = self._fast.update(value)
        slow = self._slow.update(value)
        macd_line = fast - slow
        signal = self._signal.update(macd_line)
        return MacdValue(macd=macd_line, signal=signal, histogram=macd_line - signal)

    def reset(self) -> None:
        self._fast.reset()
        self._slow.reset()
        self._signal.reset()
