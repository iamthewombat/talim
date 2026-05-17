"""Momentum strategy for US500 CFD — EMA crossover."""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, EmaStream
from talim.strategy.params import ParamSpec
from talim.strategy.validation import ValidationResult, default_validate_signal


class MomentumUS500(BaseStrategy):
    """EMA crossover momentum strategy for US500 index CFD."""

    ema_fast_period: int = 8
    ema_slow_period: int = 21
    atr_multiplier_stop: float = 1.5
    atr_multiplier_target: float = 3.0

    PARAMS = [
        ParamSpec("ema_fast_period", int, 8, min=2, max=200,
                  description="Fast EMA lookback in bars"),
        ParamSpec("ema_slow_period", int, 21, min=2, max=500,
                  description="Slow EMA lookback in bars; must be > ema_fast_period"),
        ParamSpec("atr_multiplier_stop", float, 1.5, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 3.0, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._bars_seen = 0
        self._ema_fast = EmaStream(self.ema_fast_period)
        self._ema_slow = EmaStream(self.ema_slow_period)
        self._atr = AtrStream(period=14)
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    @property
    def name(self) -> str:
        return "momentum-US500"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def validate_signal(
        self,
        signal: Signal,
        bars: list[OHLCVBar],
        *,
        atr: float | None = None,
    ) -> ValidationResult:
        base = default_validate_signal(
            signal,
            bars,
            max_bars_since_signal=3,
            max_adverse_r=0.25,
            max_favourable_r=0.75,
            atr=atr,
        )
        if not base.approval_allowed:
            return base
        if len(bars) < self.ema_slow_period:
            return ValidationResult(
                status="data_unavailable",
                approval_allowed=False,
                reason=f"need at least {self.ema_slow_period} bars for EMA validation",
                current_price=base.current_price,
                movement_r=base.movement_r,
                movement_atr=base.movement_atr,
                bars_since_signal=base.bars_since_signal,
                evaluated_at=base.evaluated_at,
            )

        fast_stream = EmaStream(self.ema_fast_period)
        slow_stream = EmaStream(self.ema_slow_period)
        fast = slow = 0.0
        for bar in bars:
            fast = fast_stream.update(bar.close)
            slow = slow_stream.update(bar.close)

        if signal.side.lower() == "long" and fast <= slow:
            return ValidationResult(
                status="condition_invalidated",
                approval_allowed=False,
                reason=f"momentum invalidated: EMA({self.ema_fast_period}) is no longer above EMA({self.ema_slow_period})",
                current_price=base.current_price,
                movement_r=base.movement_r,
                movement_atr=base.movement_atr,
                bars_since_signal=base.bars_since_signal,
                evaluated_at=base.evaluated_at,
            )
        if signal.side.lower() == "short" and fast >= slow:
            return ValidationResult(
                status="condition_invalidated",
                approval_allowed=False,
                reason=f"momentum invalidated: EMA({self.ema_fast_period}) is no longer below EMA({self.ema_slow_period})",
                current_price=base.current_price,
                movement_r=base.movement_r,
                movement_atr=base.movement_atr,
                bars_since_signal=base.bars_since_signal,
                evaluated_at=base.evaluated_at,
            )
        return ValidationResult(
            status="valid",
            approval_allowed=True,
            reason=f"momentum condition still holds: EMA({self.ema_fast_period}) remains on the signal side of EMA({self.ema_slow_period})",
            current_price=base.current_price,
            movement_r=base.movement_r,
            movement_atr=base.movement_atr,
            bars_since_signal=base.bars_since_signal,
            evaluated_at=base.evaluated_at,
        )

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        self._bars_seen += 1
        atr = self._atr.update(bar.high, bar.low, bar.close)
        self._prev_fast = self._ema_fast.value
        self._prev_slow = self._ema_slow.value
        fast = self._ema_fast.update(bar.close)
        slow = self._ema_slow.update(bar.close)

        if self._bars_seen < self.ema_slow_period:
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
                    rationale=f"EMA({self.ema_fast_period}) crossed above EMA({self.ema_slow_period})",
                    regime_context="",
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
                    rationale=f"EMA({self.ema_fast_period}) crossed below EMA({self.ema_slow_period})",
                    regime_context="",
                    timestamp=bar.timestamp,
                )
        return None
