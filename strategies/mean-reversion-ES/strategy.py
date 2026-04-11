"""Mean-reversion strategy for ES — Bollinger Band reversion."""

from __future__ import annotations

import math
from datetime import datetime

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy


class MeanReversionES(BaseStrategy):
    """Bollinger Band mean-reversion strategy for E-mini S&P 500."""

    bb_period: int = 20
    bb_std: float = 2.0
    atr_multiplier_stop: float = 2.0
    atr_multiplier_target: float = 1.5

    def __init__(self):
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._atr: float = 0.0

    @property
    def name(self) -> str:
        return "mean-reversion-ES"

    def reset(self) -> None:
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._atr = 0.0

    def _update_atr(self, high: float, low: float, prev_close: float | None) -> float:
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        period = 14
        if self._atr == 0.0:
            return tr
        k = 1.0 / period
        return tr * k + self._atr * (1 - k)

    def _bollinger(self) -> tuple[float, float, float] | None:
        """Return (middle, upper, lower) Bollinger Bands, or None if not enough data."""
        if len(self._closes) < self.bb_period:
            return None
        window = self._closes[-self.bb_period :]
        middle = sum(window) / self.bb_period
        variance = sum((x - middle) ** 2 for x in window) / self.bb_period
        std = math.sqrt(variance)
        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std
        return middle, upper, lower

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        prev_close = self._closes[-1] if self._closes else None
        self._closes.append(bar.close)
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        # Update ATR
        self._atr = self._update_atr(bar.high, bar.low, prev_close)

        bands = self._bollinger()
        if bands is None:
            return None

        middle, upper, lower = bands

        # Long signal: price touches or breaks below lower band (expect reversion up)
        if bar.close <= lower and prev_close is not None and prev_close > lower:
            stop = bar.close - self._atr * self.atr_multiplier_stop
            target = bar.close + self._atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="long",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Price broke below lower BB({self.bb_period}, {self.bb_std}σ) — expecting reversion",
                regime_context="",
                timestamp=bar.timestamp,
            )

        # Short signal: price touches or breaks above upper band (expect reversion down)
        if bar.close >= upper and prev_close is not None and prev_close < upper:
            stop = bar.close + self._atr * self.atr_multiplier_stop
            target = bar.close - self._atr * self.atr_multiplier_target
            return Signal(
                instrument=bar.instrument,
                strategy=self.name,
                side="short",
                entry_price=bar.close,
                stop=round(stop, 2),
                target=round(target, 2),
                rationale=f"Price broke above upper BB({self.bb_period}, {self.bb_std}σ) — expecting reversion",
                regime_context="",
                timestamp=bar.timestamp,
            )

        return None
