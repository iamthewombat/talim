"""N-consecutive-down-days pullback benchmark — instrument-agnostic, long only.

Public defaults (classic short-term pullback study, e.g. Sweeney/Alvarez
down-days tests): above the 200-bar SMA, buy at the close after 3 consecutive
lower closes; exit at the close on the first up close, via the condition-exit
hook. A wide ATR stop is protective only. No profit target.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, SmaStream
from talim.strategy.params import ParamSpec


class DownDaysPullback(BaseStrategy):
    """Long after N consecutive lower closes above the 200-SMA; exit on the first up close."""

    down_days: int = 3
    trend_sma_period: int = 200
    atr_multiplier_stop: float = 5.0

    PARAMS = [
        ParamSpec("down_days", int, 3, min=1, max=20,
                  description="Enter after this many consecutive lower closes"),
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
        self._down_streak = 0
        # close of the bar before the one on_bar last processed, then the
        # last processed close — exit_signal runs after on_bar for the same
        # bar, so "previous close" for that bar is _closes[0]
        self._prev_close: float | None = None
        self._prev_prev_close: float | None = None

    @property
    def name(self) -> str:
        return "down-days-pullback"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        if side != "long":
            return False
        if self._prev_prev_close is None:
            return False
        return bar.close > self._prev_prev_close

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        sma = self._sma.update(bar.close)

        if self._prev_close is not None:
            if bar.close < self._prev_close:
                self._down_streak += 1
            elif bar.close > self._prev_close:
                self._down_streak = 0
        self._prev_prev_close = self._prev_close
        self._prev_close = bar.close

        if self._down_streak < self.down_days:
            return None
        if sma is None or atr is None or atr <= 0:
            return None
        if bar.close <= sma:
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
                f"Pullback: {self._down_streak} consecutive down closes "
                f"above SMA({self.trend_sma_period})"
            ),
            regime_context="",
            timestamp=bar.timestamp,
        )
