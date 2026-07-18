"""Mean-reversion strategy for US500 CFD — Bollinger Band reversion."""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, BollingerStream
from talim.strategy.params import ParamSpec
from talim.strategy.validation import ValidationResult, default_validate_signal


class MeanReversionUS500(BaseStrategy):
    """Bollinger Band mean-reversion strategy for US500 index CFD."""

    bb_period: int = 20
    bb_std: float = 2.0
    atr_multiplier_stop: float = 2.0
    atr_multiplier_target: float = 1.5

    PARAMS = [
        ParamSpec("bb_period", int, 20, min=2, max=500,
                  description="Bollinger Band window length in bars"),
        ParamSpec("bb_std", float, 2.0, min=0.1, max=10.0,
                  description="Bollinger Band width in standard deviations"),
        ParamSpec("atr_multiplier_stop", float, 2.0, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 1.5, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._bb = BollingerStream(self.bb_period, self.bb_std)
        self._prev_close: float | None = None
        self._last_bands = None

    @property
    def name(self) -> str:
        return "mean-reversion-US500"

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
            max_bars_since_signal=2,
            max_adverse_r=0.20,
            max_favourable_r=0.65,
            atr=atr,
        )
        if not base.approval_allowed:
            return base
        bb = BollingerStream(self.bb_period, self.bb_std)
        bands = None
        for bar in bars:
            bands = bb.update(bar.close)
        if bands is None:
            return ValidationResult(
                status="data_unavailable",
                approval_allowed=False,
                reason=f"need at least {self.bb_period} bars for Bollinger validation",
                current_price=base.current_price,
                movement_r=base.movement_r,
                movement_atr=base.movement_atr,
                bars_since_signal=base.bars_since_signal,
                evaluated_at=base.evaluated_at,
            )
        current = bars[-1].close
        if signal.side.lower() == "long" and current >= bands.middle:
            return ValidationResult("condition_invalidated", False, "mean reversion invalidated: price has already reverted to/through the Bollinger midline", current, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)
        if signal.side.lower() == "short" and current <= bands.middle:
            return ValidationResult("condition_invalidated", False, "mean reversion invalidated: price has already reverted to/through the Bollinger midline", current, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)
        return ValidationResult("valid", True, "mean-reversion condition remains before Bollinger midline reversion", current, base.movement_r, base.movement_atr, base.bars_since_signal, base.evaluated_at)

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        bands = self._last_bands
        if bands is None:
            return False
        if side == "long":
            return bar.close >= bands.middle
        return bar.close <= bands.middle

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        bands = self._bb.update(bar.close)
        self._last_bands = bands
        prev_close = self._prev_close
        self._prev_close = bar.close

        if bands is None or prev_close is None:
            return None

        # Long: price crosses below the lower band (expect reversion up)
        if bar.close <= bands.lower and prev_close > bands.lower:
            stop = bar.close - atr * self.atr_multiplier_stop
            target = bar.close + atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Price broke below lower BB({self.bb_period}, {self.bb_std}σ) — expecting reversion",
                regime_context="",
                timestamp=bar.timestamp,
            )

        # Short: price crosses above the upper band (expect reversion down)
        if bar.close >= bands.upper and prev_close < bands.upper:
            stop = bar.close + atr * self.atr_multiplier_stop
            target = bar.close - atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Price broke above upper BB({self.bb_period}, {self.bb_std}σ) — expecting reversion",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
