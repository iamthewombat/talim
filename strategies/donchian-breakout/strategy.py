"""Donchian channel breakout benchmark (Turtle-style) — instrument-agnostic.

Public defaults: enter on close breaking the prior 20-bar channel extreme.
The channel from the previous bar is used so the breakout bar's own
high/low cannot satisfy its own trigger. Exits are ATR brackets.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, DonchianStream
from talim.strategy.params import ParamSpec


class DonchianBreakout(BaseStrategy):
    """Donchian 20-bar breakout with ATR bracket exits."""

    channel_period: int = 20
    atr_multiplier_stop: float = 2.0
    atr_multiplier_target: float = 3.0

    PARAMS = [
        ParamSpec("channel_period", int, 20, min=2, max=500,
                  description="Donchian channel lookback in bars"),
        ParamSpec("atr_multiplier_stop", float, 2.0, min=0.1, max=20.0,
                  description="Stop distance as a multiple of ATR"),
        ParamSpec("atr_multiplier_target", float, 3.0, min=0.1, max=20.0,
                  description="Take-profit distance as a multiple of ATR"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._donchian = DonchianStream(period=self.channel_period)
        self._prev_channel = None

    @property
    def name(self) -> str:
        return "donchian-breakout"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        prev_channel = self._prev_channel
        self._prev_channel = self._donchian.update(bar.high, bar.low)

        if prev_channel is None or atr is None or atr <= 0:
            return None

        if bar.close > prev_channel.upper:
            stop = bar.close - atr * self.atr_multiplier_stop
            target = bar.close + atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Close broke above {self.channel_period}-bar Donchian upper ({prev_channel.upper:.2f})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        if bar.close < prev_channel.lower:
            stop = bar.close + atr * self.atr_multiplier_stop
            target = bar.close - atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Close broke below {self.channel_period}-bar Donchian lower ({prev_channel.lower:.2f})",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
