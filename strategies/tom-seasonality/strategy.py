"""Turn-of-month seasonality benchmark — instrument-agnostic, long only.

Public defaults (McConnell & Xu-style window): buy at the close once the
calendar date is within the last `days_before_eom` days of the month, hold
through the first `hold_days` trading days of the new month, exit at that
bar's close. Time-based exit via the condition-exit hook; a wide ATR stop
is protective only. No profit target.
"""

from __future__ import annotations

import calendar

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream
from talim.strategy.params import ParamSpec


class TomSeasonality(BaseStrategy):
    """Long the turn-of-month window on daily bars."""

    days_before_eom: int = 4
    hold_days: int = 3
    atr_multiplier_stop: float = 5.0

    PARAMS = [
        ParamSpec("days_before_eom", int, 4, min=1, max=15,
                  description="Enter when within this many calendar days of month end"),
        ParamSpec("hold_days", int, 3, min=1, max=15,
                  description="Exit at the close of this trading day of the new month"),
        ParamSpec("atr_multiplier_stop", float, 5.0, min=0.5, max=20.0,
                  description="Protective stop distance as a multiple of ATR (wide; exit is time-based)"),
    ]

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._atr = AtrStream(period=14)
        self._month: tuple[int, int] | None = None
        self._bars_in_month: int = 0
        self._in_entry_window: bool = False

    @property
    def name(self) -> str:
        return "tom-seasonality"

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        # Hold while still in the entry window (end of the entry month);
        # exit once the new month has printed `hold_days` bars.
        if self._in_entry_window:
            return False
        return self._bars_in_month >= self.hold_days

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)

        month_key = (bar.timestamp.year, bar.timestamp.month)
        if month_key != self._month:
            self._month = month_key
            self._bars_in_month = 0
        self._bars_in_month += 1

        month_end_day = calendar.monthrange(bar.timestamp.year, bar.timestamp.month)[1]
        self._in_entry_window = (month_end_day - bar.timestamp.day) < self.days_before_eom

        if not self._in_entry_window or atr is None or atr <= 0:
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
                f"Turn-of-month: day {bar.timestamp.day}/{month_end_day}, "
                f"holding through first {self.hold_days} trading days of next month"
            ),
            regime_context="",
            timestamp=bar.timestamp,
        )
