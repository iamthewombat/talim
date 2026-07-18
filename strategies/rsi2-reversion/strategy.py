"""RSI(2) mean-reversion benchmark (Connors-style) — instrument-agnostic.

Public defaults: buy RSI(2) < 10 above the 200-bar SMA, short RSI(2) > 90
below it. Exits are ATR brackets (engine constraint; classic SMA(5)/midline
exits need indicator-condition exit support).
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, RsiStream, SmaStream
from talim.strategy.params import ParamSpec


class Rsi2Reversion(BaseStrategy):
    """RSI(2) extreme mean reversion with 200-SMA trend filter."""

    rsi_period: int = 2
    rsi_entry: float = 10.0
    trend_sma_period: int = 200
    exit_sma_period: int = 5
    atr_multiplier_stop: float = 2.0
    atr_multiplier_target: float = 1.5

    PARAMS = [
        ParamSpec("rsi_period", int, 2, min=1, max=100,
                  description="RSI lookback in bars"),
        ParamSpec("rsi_entry", float, 10.0, min=0.5, max=49.0,
                  description="Long entry when RSI below this; short entry mirrored above 100 - value"),
        ParamSpec("trend_sma_period", int, 200, min=10, max=1000,
                  description="SMA trend filter length; longs only above it, shorts only below"),
        ParamSpec("exit_sma_period", int, 5, min=1, max=100,
                  description="Condition exit: close crossing this SMA closes the position (Connors exit)"),
        ParamSpec("atr_multiplier_stop", float, 2.0, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 1.5, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._rsi = RsiStream(period=self.rsi_period)
        self._sma = SmaStream(period=self.trend_sma_period)
        self._exit_sma = SmaStream(period=self.exit_sma_period)
        self._last_exit_sma: float | None = None

    @property
    def name(self) -> str:
        return "rsi2-reversion"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        if self._last_exit_sma is None:
            return False
        if side == "long":
            return bar.close > self._last_exit_sma
        return bar.close < self._last_exit_sma

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        rsi = self._rsi.update(bar.close)
        sma = self._sma.update(bar.close)
        self._last_exit_sma = self._exit_sma.update(bar.close)

        if rsi is None or sma is None or atr is None or atr <= 0:
            return None

        if rsi <= self.rsi_entry and bar.close > sma:
            stop = bar.close - atr * self.atr_multiplier_stop
            target = bar.close + atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"RSI({self.rsi_period})={rsi:.1f} <= {self.rsi_entry} above SMA({self.trend_sma_period}) — oversold in uptrend",
                regime_context="",
                timestamp=bar.timestamp,
            )

        if rsi >= 100.0 - self.rsi_entry and bar.close < sma:
            stop = bar.close + atr * self.atr_multiplier_stop
            target = bar.close - atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"RSI({self.rsi_period})={rsi:.1f} >= {100.0 - self.rsi_entry:.0f} below SMA({self.trend_sma_period}) — overbought in downtrend",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
