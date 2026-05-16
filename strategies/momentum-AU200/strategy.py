"""Momentum strategy for AU200 CFDs."""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, EmaStream
from talim.strategy.params import ParamSpec
from talim.strategy.validation import ValidationResult, default_validate_signal


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
        atr_stream = AtrStream(period=self.atr_period)
        fast = slow = atr_now = 0.0
        for bar in bars:
            atr_now = atr_stream.update(bar.high, bar.low, bar.close)
            fast = fast_stream.update(bar.close)
            slow = slow_stream.update(bar.close)
        if atr_now > 0 and abs(fast - slow) < self.min_ema_gap_atr * atr_now:
            return ValidationResult(
                status="condition_invalidated",
                approval_allowed=False,
                reason="momentum invalidated: EMA separation is below the ATR-backed threshold",
                current_price=base.current_price,
                movement_r=base.movement_r,
                movement_atr=base.movement_atr,
                bars_since_signal=base.bars_since_signal,
                evaluated_at=base.evaluated_at,
            )
        if signal.side.lower() == "long" and fast <= slow:
            return ValidationResult("condition_invalidated", False, f"momentum invalidated: EMA({self.ema_fast_period}) is no longer above EMA({self.ema_slow_period})", base.current_price, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)
        if signal.side.lower() == "short" and fast >= slow:
            return ValidationResult("condition_invalidated", False, f"momentum invalidated: EMA({self.ema_fast_period}) is no longer below EMA({self.ema_slow_period})", base.current_price, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)
        return ValidationResult("valid", True, "momentum condition and ATR-backed separation still hold", base.current_price, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)

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
