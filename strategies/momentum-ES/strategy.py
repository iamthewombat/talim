"""Momentum strategy for ES — EMA crossover."""

from __future__ import annotations

from datetime import datetime

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy


class MomentumES(BaseStrategy):
    """EMA crossover momentum strategy for E-mini S&P 500."""

    ema_fast_period: int = 8
    ema_slow_period: int = 21
    atr_multiplier_stop: float = 1.5
    atr_multiplier_target: float = 3.0

    def __init__(self):
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._prev_ema_fast: float | None = None
        self._prev_ema_slow: float | None = None
        self._atr: float = 0.0

    @property
    def name(self) -> str:
        return "momentum-ES"

    def reset(self) -> None:
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._ema_fast = None
        self._ema_slow = None
        self._prev_ema_fast = None
        self._prev_ema_slow = None
        self._atr = 0.0

    def _update_ema(self, value: float, prev_ema: float | None, period: int) -> float:
        if prev_ema is None:
            return value
        k = 2.0 / (period + 1)
        return value * k + prev_ema * (1 - k)

    def _update_atr(self, high: float, low: float, prev_close: float | None) -> float:
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        period = 14
        if self._atr == 0.0:
            return tr
        k = 1.0 / period
        return tr * k + self._atr * (1 - k)

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        prev_close = self._closes[-1] if self._closes else None
        self._closes.append(bar.close)
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        # Update ATR
        self._atr = self._update_atr(bar.high, bar.low, prev_close)

        # Update EMAs
        self._prev_ema_fast = self._ema_fast
        self._prev_ema_slow = self._ema_slow
        self._ema_fast = self._update_ema(bar.close, self._ema_fast, self.ema_fast_period)
        self._ema_slow = self._update_ema(bar.close, self._ema_slow, self.ema_slow_period)

        # Need at least slow period bars for meaningful signal
        if len(self._closes) < self.ema_slow_period:
            return None

        # Check for bullish crossover: fast crosses above slow
        if (
            self._prev_ema_fast is not None
            and self._prev_ema_slow is not None
            and self._prev_ema_fast <= self._prev_ema_slow
            and self._ema_fast > self._ema_slow
        ):
            stop = bar.close - self._atr * self.atr_multiplier_stop
            target = bar.close + self._atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"EMA({self.ema_fast_period}) crossed above EMA({self.ema_slow_period})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        # Check for bearish crossover: fast crosses below slow
        if (
            self._prev_ema_fast is not None
            and self._prev_ema_slow is not None
            and self._prev_ema_fast >= self._prev_ema_slow
            and self._ema_fast < self._ema_slow
        ):
            stop = bar.close + self._atr * self.atr_multiplier_stop
            target = bar.close - self._atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"EMA({self.ema_fast_period}) crossed below EMA({self.ema_slow_period})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
