"""Opening Range Breakout (ORB) benchmark — session-effects family.

Trades the break of the first `opening_range_minutes` of the cash session:
long on a close above the range high, short on a close below the range low,
one entry per day. Stop at the opposite side of the range, target at
`target_r` x range width, forced flat outside session hours.

Session open/close are instrument facts (minutes since midnight UTC), not
tunables: US500 cash = 870-1260 (14:30-21:00 UTC), AU200 cash = 0-360
(00:00-06:00 UTC). Fixed-UTC sessions smear across exchange DST shifts —
a known limitation of this benchmark.
"""

from __future__ import annotations

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.params import ParamSpec


class OrbBreakout(BaseStrategy):
    """Opening range breakout with range-edge stop and R-multiple target."""

    opening_range_minutes: int = 30
    target_r: float = 2.0
    session_open_minute: int = 870
    session_close_minute: int = 1260

    PARAMS = [
        ParamSpec("opening_range_minutes", int, 30, min=5, max=240,
                  description="Opening range length in minutes from session open"),
        ParamSpec("target_r", float, 2.0, min=0.1, max=10.0,
                  description="Take-profit distance as a multiple of the opening range width"),
        ParamSpec("session_open_minute", int, 870, min=0, max=1439,
                  description="Cash session open, minutes since midnight UTC (instrument fact, not a tunable)"),
        ParamSpec("session_close_minute", int, 1260, min=0, max=1439,
                  description="Cash session close, minutes since midnight UTC (instrument fact, not a tunable)"),
    ]

    def __init__(self) -> None:
        self._reset_day_state(None)

    def _reset_day_state(self, day) -> None:
        self._day = day
        self._range_high: float | None = None
        self._range_low: float | None = None
        self._entered_today = False

    @property
    def name(self) -> str:
        return "orb-breakout"

    def reset(self) -> None:
        self._reset_day_state(None)

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._reset_day_state(None)

    @staticmethod
    def _minute_of_day(ts) -> int:
        return ts.hour * 60 + ts.minute

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        mod = self._minute_of_day(bar.timestamp)
        open_m, close_m = self.session_open_minute, self.session_close_minute
        if open_m <= close_m:
            return not (open_m <= mod < close_m)
        return close_m <= mod < open_m

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        day = bar.timestamp.date()
        if day != self._day:
            self._reset_day_state(day)

        mod = self._minute_of_day(bar.timestamp)
        open_m = self.session_open_minute
        range_end = open_m + self.opening_range_minutes

        if open_m <= mod < range_end:
            self._range_high = bar.high if self._range_high is None else max(self._range_high, bar.high)
            self._range_low = bar.low if self._range_low is None else min(self._range_low, bar.low)
            return None

        if (
            self._range_high is None
            or self._entered_today
            or not (range_end <= mod < self.session_close_minute)
        ):
            return None

        width = self._range_high - self._range_low
        if width <= 0:
            return None

        if bar.close > self._range_high:
            self._entered_today = True
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(self._range_low, 2),
                target=round(bar.close + self.target_r * width, 2),
                rationale=f"Close broke above {self.opening_range_minutes}m opening range high {self._range_high:.2f}",
                regime_context="",
                timestamp=bar.timestamp,
            )

        if bar.close < self._range_low:
            self._entered_today = True
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(self._range_high, 2),
                target=round(bar.close - self.target_r * width, 2),
                rationale=f"Close broke below {self.opening_range_minutes}m opening range low {self._range_low:.2f}",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
