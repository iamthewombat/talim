"""Internal Bar Strength (IBS) mean reversion benchmark — instrument-agnostic, long only.

Public defaults (Pagonidis/QUSMA-documented equity-index effect): IBS =
(close - low) / (high - low). Buy at the close when the bar closes near its
low (IBS < `ibs_entry`); exit at the close once a bar closes near its high
(IBS > `ibs_exit`), via the condition-exit hook. A wide ATR stop is
protective only. No profit target.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream
from talim.strategy.params import ParamSpec


def _ibs(bar: OHLCVBar) -> float | None:
    bar_range = bar.high - bar.low
    if bar_range <= 0:
        return None
    return (bar.close - bar.low) / bar_range


class IbsReversion(BaseStrategy):
    """Long when the bar closes near its low; exit when it closes near its high."""

    ibs_entry: float = 0.2
    ibs_exit: float = 0.8
    atr_multiplier_stop: float = 5.0

    PARAMS = [
        ParamSpec("ibs_entry", float, 0.2, min=0.01, max=0.5,
                  description="Enter long when IBS closes below this level"),
        ParamSpec("ibs_exit", float, 0.8, min=0.5, max=0.99,
                  description="Exit at the close once IBS closes above this level"),
        ParamSpec("atr_multiplier_stop", float, 5.0, min=0.5, max=20.0,
                  description="Protective stop distance as a multiple of ATR (wide; exit is condition-based)"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)

    @property
    def name(self) -> str:
        return "ibs-reversion"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        if side != "long":
            return False
        ibs = _ibs(bar)
        return ibs is not None and ibs > self.ibs_exit

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)

        ibs = _ibs(bar)
        if ibs is None or ibs >= self.ibs_entry:
            return None
        if atr is None or atr <= 0:
            return None

        stop = bar.close - atr * self.atr_multiplier_stop
        return Signal(
            instrument=bar.instrument,
            strategy=self.name,
            side="long",
            entry_price=bar.close,
            stop=round(stop, 2),
            target=0.0,
            rationale=f"IBS reversion: bar closed at IBS {ibs:.2f} < {self.ibs_entry}",
            regime_context="",
            timestamp=bar.timestamp,
        )
