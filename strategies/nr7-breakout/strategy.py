"""NR7 narrow-range breakout benchmark (Crabel-style) — instrument-agnostic.

Public defaults: when the previous bar has the narrowest high-low range of
the trailing `nr_period` bars (NR7), a close above that bar's high goes
long and a close below its low goes short. Exits are ATR brackets.
"""

from __future__ import annotations

from collections import deque

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream
from talim.strategy.params import ParamSpec


class Nr7Breakout(BaseStrategy):
    """Breakout from the narrowest range of the trailing N bars."""

    nr_period: int = 7
    atr_multiplier_stop: float = 2.0
    atr_multiplier_target: float = 3.0

    PARAMS = [
        ParamSpec("nr_period", int, 7, min=3, max=50,
                  description="Bar qualifies when its range is the narrowest of this many trailing bars"),
        ParamSpec("atr_multiplier_stop", float, 2.0, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 3.0, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._ranges: deque[float] = deque(maxlen=self.nr_period)
        self._prev_bar: OHLCVBar | None = None
        self._prev_was_nr: bool = False

    @property
    def name(self) -> str:
        return "nr7-breakout"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)

        prev_bar = self._prev_bar
        prev_was_nr = self._prev_was_nr

        bar_range = bar.high - bar.low
        self._ranges.append(bar_range)
        self._prev_bar = bar
        self._prev_was_nr = (
            len(self._ranges) == self.nr_period and bar_range <= min(self._ranges)
        )

        if not prev_was_nr or prev_bar is None or atr is None or atr <= 0:
            return None

        if bar.close > prev_bar.high:
            stop = bar.close - atr * self.atr_multiplier_stop
            target = bar.close + atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"NR{self.nr_period} breakout: close above narrow-range bar high ({prev_bar.high:.2f})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        if bar.close < prev_bar.low:
            stop = bar.close + atr * self.atr_multiplier_stop
            target = bar.close - atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"NR{self.nr_period} breakout: close below narrow-range bar low ({prev_bar.low:.2f})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
