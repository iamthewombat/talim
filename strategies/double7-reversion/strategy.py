"""Connors Double 7 mean-reversion benchmark — instrument-agnostic, long only.

Public defaults (Connors/Alvarez "Short Term Trading Strategies That Work"):
above the 200-bar SMA, buy at the close when the close is the lowest close of
the last 7 bars; exit at the close when it is the highest close of the last
7 bars, via the condition-exit hook. A wide ATR stop is protective only.
No profit target.
"""

from __future__ import annotations

from collections import deque

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, SmaStream
from talim.strategy.params import ParamSpec


class Double7Reversion(BaseStrategy):
    """Long at a 7-bar closing low above the 200-SMA; exit at a 7-bar closing high."""

    lookback: int = 7
    trend_sma_period: int = 200
    atr_multiplier_stop: float = 5.0

    PARAMS = [
        ParamSpec("lookback", int, 7, min=2, max=100,
                  description="Enter at an N-bar closing low; exit at an N-bar closing high"),
        ParamSpec("trend_sma_period", int, 200, min=10, max=1000,
                  description="SMA trend filter length; longs only above it"),
        ParamSpec("atr_multiplier_stop", float, 5.0, min=0.5, max=20.0,
                  description="Protective stop distance as a multiple of ATR (wide; exit is condition-based)"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._sma = SmaStream(period=self.trend_sma_period)
        self._closes: deque[float] = deque(maxlen=self.lookback)

    @property
    def name(self) -> str:
        return "double7-reversion"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        if side != "long":
            return False
        if len(self._closes) < self.lookback:
            return False
        return bar.close >= max(self._closes)

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        sma = self._sma.update(bar.close)
        self._closes.append(bar.close)

        if len(self._closes) < self.lookback:
            return None
        if sma is None or atr is None or atr <= 0:
            return None
        if bar.close > min(self._closes) or bar.close <= sma:
            return None

        stop = bar.close - atr * self.atr_multiplier_stop
        return Signal(
            instrument=bar.instrument,
            strategy=self.name,
            side="long",
            entry_price=bar.close,
            stop=round(stop, 2),
            target=0.0,
            rationale=(
                f"Double 7: close is the lowest close of {self.lookback} bars "
                f"above SMA({self.trend_sma_period})"
            ),
            regime_context="",
            timestamp=bar.timestamp,
        )
