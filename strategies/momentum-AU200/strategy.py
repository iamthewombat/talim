"""Momentum strategy for AU200 CFDs."""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, EmaStream
from talim.strategy.params import ParamSpec


class MomentumAU200(BaseStrategy):
    """Trend-following EMA crossover with an ATR separation filter."""

    ema_fast_period: int = 13
    ema_slow_period: int = 34
    atr_period: int = 14
    atr_multiplier_stop: float = 1.6
    atr_multiplier_target: float = 2.8
    min_ema_gap_atr: float = 0.12

    PARAMS = [
        ParamSpec("ema_fast_period", int, 13, min=2, max=200,
                  description="Fast EMA lookback in bars"),
        ParamSpec("ema_slow_period", int, 34, min=2, max=500,
                  description="Slow EMA lookback in bars; must be > ema_fast_period"),
        ParamSpec("atr_period", int, 14, min=2, max=200,
                  description="ATR lookback in bars"),
        ParamSpec("atr_multiplier_stop", float, 1.6, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 2.8, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
        ParamSpec("min_ema_gap_atr", float, 0.12, min=0.0, max=5.0,
                  description="Minimum EMA separation in ATR units required to fire a signal"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._bars_seen = 0
        self._ema_fast = EmaStream(self.ema_fast_period)
        self._ema_slow = EmaStream(self.ema_slow_period)
        self._atr = AtrStream(period=self.atr_period)
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    @property
    def name(self) -> str:
        return "momentum-AU200"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        self._bars_seen += 1
        atr = self._atr.update(bar.high, bar.low, bar.close)
        self._prev_fast = self._ema_fast.value
        self._prev_slow = self._ema_slow.value
        fast = self._ema_fast.update(bar.close)
        slow = self._ema_slow.update(bar.close)

        if self._bars_seen < self.ema_slow_period:
            return None

        ema_gap = abs(fast - slow)
        if atr > 0 and ema_gap < self.min_ema_gap_atr * atr:
            return None

        if self._prev_fast is not None and self._prev_slow is not None:
            if self._prev_fast <= self._prev_slow and fast > slow:
                stop = bar.close - atr * self.atr_multiplier_stop
                target = bar.close + atr * self.atr_multiplier_target
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

            if self._prev_fast >= self._prev_slow and fast < slow:
                stop = bar.close + atr * self.atr_multiplier_stop
                target = bar.close - atr * self.atr_multiplier_target
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
