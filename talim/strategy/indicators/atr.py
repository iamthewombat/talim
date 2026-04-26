"""Average True Range — Wilder smoothing (RMA).

This implementation matches the inline ATR computation that has been used in
the existing Talim strategies: the first bar's true range is its
(high - low), and subsequent bars smooth with ``k = 1 / period``. Using this
module keeps numerical behaviour identical after the WP-71 refactor.

For the rolling-mean ATR used by the regime engine, see
``talim.regime.fingerprint.compute_atr``; the two are intentionally distinct
because they answer different questions.
"""

from __future__ import annotations

from collections.abc import Sequence


def _true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return float(high) - float(low)
    return max(
        float(high) - float(low),
        abs(float(high) - float(prev_close)),
        abs(float(low) - float(prev_close)),
    )


def atr_wilder(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float]:
    """Vectorised Wilder ATR.

    Initialises from the first bar's true range and smooths with ``1/period``.
    The first output equals ``highs[0] - lows[0]``.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs, lows, closes must be the same length")
    if n == 0:
        return []
    out: list[float] = []
    atr = 0.0
    k = 1.0 / period
    for i in range(n):
        prev_close = float(closes[i - 1]) if i > 0 else None
        tr = _true_range(highs[i], lows[i], prev_close)
        atr = tr if atr == 0.0 else tr * k + atr * (1 - k)
        out.append(atr)
    return out


class AtrStream:
    """Streaming Wilder ATR. Returns the updated value on every bar.

    Preserves the existing strategy semantics: initialises from the first
    bar's true range, uses ``1/period`` smoothing, treats ``atr == 0.0`` as
    the "uninitialised" sentinel.
    """

    __slots__ = ("period", "_k", "_atr", "_prev_close")

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._k = 1.0 / period
        self._atr = 0.0
        self._prev_close: float | None = None

    @property
    def value(self) -> float:
        return self._atr

    def update(self, high: float, low: float, close: float) -> float:
        tr = _true_range(high, low, self._prev_close)
        if self._atr == 0.0:
            self._atr = tr
        else:
            self._atr = tr * self._k + self._atr * (1 - self._k)
        self._prev_close = float(close)
        return self._atr

    def reset(self) -> None:
        self._atr = 0.0
        self._prev_close = None
