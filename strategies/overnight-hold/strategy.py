"""Overnight session hold benchmark — long only, time-based entry/exit.

Public spec (documented US equity overnight anomaly): buy at the cash-session
close, exit at the first bar close after the next cash open. On open-stamped
1h bars: enter at the close of the `entry_hour_utc` bar (20:00 bar closes
21:00 UTC = US cash close, winter), exit at the close of the `exit_hour_utc`
bar (14:00 bar closes 15:00 UTC, just after the 14:30 cash open). Hour params
are instrument facts, not tunables; fixed UTC smears across exchange DST
shifts (same known limitation as orb-breakout). Friday entries hold the
weekend, per the classic close-to-open studies. A wide ATR stop is protective
only. No profit target.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream
from talim.strategy.params import ParamSpec


class OvernightHold(BaseStrategy):
    """Long at the cash close; exit at the first bar close after the next cash open."""

    entry_hour_utc: int = 20
    exit_hour_utc: int = 14
    atr_multiplier_stop: float = 5.0

    PARAMS = [
        ParamSpec("entry_hour_utc", int, 20, min=0, max=23,
                  description="Enter at the close of the bar opening at this UTC hour (cash-close bar)"),
        ParamSpec("exit_hour_utc", int, 14, min=0, max=23,
                  description="Exit at the close of the bar opening at this UTC hour (first bar spanning the cash open)"),
        ParamSpec("atr_multiplier_stop", float, 5.0, min=0.5, max=20.0,
                  description="Protective stop distance as a multiple of ATR (wide; exit is time-based)"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)

    @property
    def name(self) -> str:
        return "overnight-hold"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        return side == "long" and bar.timestamp.hour == self.exit_hour_utc

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)

        if bar.timestamp.hour != self.entry_hour_utc:
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
            rationale=f"Overnight hold: cash-close bar ({self.entry_hour_utc}:00 UTC open)",
            regime_context="",
            timestamp=bar.timestamp,
        )
