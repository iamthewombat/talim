"""Momentum strategy for AU200 CFDs."""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy


class MomentumAU200(BaseStrategy):
    """Trend-following EMA crossover with an ATR separation filter."""

    ema_fast_period: int = 13
    ema_slow_period: int = 34
    atr_period: int = 14
    atr_multiplier_stop: float = 1.6
    atr_multiplier_target: float = 2.8
    min_ema_gap_atr: float = 0.12

    def __init__(self) -> None:
        self._closes: list[float] = []
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._prev_ema_fast: float | None = None
        self._prev_ema_slow: float | None = None
        self._atr: float = 0.0

    @property
    def name(self) -> str:
        return "momentum-AU200"

    def reset(self) -> None:
        self._closes.clear()
        self._ema_fast = None
        self._ema_slow = None
        self._prev_ema_fast = None
        self._prev_ema_slow = None
        self._atr = 0.0

    @staticmethod
    def _update_ema(value: float, prev_ema: float | None, period: int) -> float:
        if prev_ema is None:
            return value
        k = 2.0 / (period + 1)
        return value * k + prev_ema * (1 - k)

    def _update_atr(self, bar: OHLCVBar, prev_close: float | None) -> float:
        if prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
        if self._atr == 0.0:
            return tr
        k = 1.0 / self.atr_period
        return tr * k + self._atr * (1 - k)

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        prev_close = self._closes[-1] if self._closes else None
        self._closes.append(bar.close)

        self._atr = self._update_atr(bar, prev_close)
        self._prev_ema_fast = self._ema_fast
        self._prev_ema_slow = self._ema_slow
        self._ema_fast = self._update_ema(bar.close, self._ema_fast, self.ema_fast_period)
        self._ema_slow = self._update_ema(bar.close, self._ema_slow, self.ema_slow_period)

        if len(self._closes) < self.ema_slow_period:
            return None

        if self._ema_fast is None or self._ema_slow is None:
            return None
        ema_gap = abs(self._ema_fast - self._ema_slow)
        if self._atr > 0 and ema_gap < self.min_ema_gap_atr * self._atr:
            return None

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
                rationale=(
                    f"EMA({self.ema_fast_period}) crossed above "
                    f"EMA({self.ema_slow_period}) with ATR-backed separation"
                ),
                regime_context="trend",
                timestamp=bar.timestamp,
            )

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
                rationale=(
                    f"EMA({self.ema_fast_period}) crossed below "
                    f"EMA({self.ema_slow_period}) with ATR-backed separation"
                ),
                regime_context="trend",
                timestamp=bar.timestamp,
            )

        return None
