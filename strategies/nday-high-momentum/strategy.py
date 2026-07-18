"""N-day-high time-series momentum benchmark — instrument-agnostic, long only.

Public defaults (52-week-high momentum, George & Hwang direction): enter long
when the close breaks the prior `lookback`-bar high; exit when the close
breaks the prior `exit_lookback`-bar low (condition exit at the close), with
a protective ATR stop. No profit target — the exit channel trails the trend.
Prior-bar channels are used so a bar cannot satisfy its own trigger.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, DonchianStream
from talim.strategy.params import ParamSpec


class NdayHighMomentum(BaseStrategy):
    """Long breakouts to an N-day high with a trailing channel exit."""

    lookback: int = 252
    exit_lookback: int = 63
    atr_multiplier_stop: float = 3.0

    PARAMS = [
        ParamSpec("lookback", int, 252, min=10, max=1000,
                  description="Entry channel: close above the prior N-bar high goes long"),
        ParamSpec("exit_lookback", int, 63, min=5, max=500,
                  description="Exit channel: close below the prior N-bar low closes the position"),
        ParamSpec("atr_multiplier_stop", float, 3.0, min=0.5, max=20.0,
                  description="Protective stop distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._entry_channel = DonchianStream(period=self.lookback)
        self._exit_channel = DonchianStream(period=self.exit_lookback)
        self._prev_entry_upper: float | None = None
        self._prev_exit_lower: float | None = None

    @property
    def name(self) -> str:
        return "nday-high-momentum"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        if side != "long" or self._prev_exit_lower is None:
            return False
        return bar.close < self._prev_exit_lower

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        prev_entry_upper = self._prev_entry_upper
        prev_exit_lower = self._prev_exit_lower

        entry_channel = self._entry_channel.update(bar.high, bar.low)
        exit_channel = self._exit_channel.update(bar.high, bar.low)
        self._prev_entry_upper = entry_channel.upper if entry_channel else None
        self._prev_exit_lower = exit_channel.lower if exit_channel else None

        if prev_entry_upper is None or prev_exit_lower is None:
            return None
        if atr is None or atr <= 0:
            return None

        if bar.close > prev_entry_upper:
            stop = bar.close - atr * self.atr_multiplier_stop
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=0.0,
                rationale=(
                    f"Close broke {self.lookback}-bar high ({prev_entry_upper:.2f}); "
                    f"trailing exit at {self.exit_lookback}-bar low"
                ),
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
