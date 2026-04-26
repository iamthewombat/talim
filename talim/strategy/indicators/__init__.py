"""Shared technical indicators for Talim strategies.

Every indicator exposes:
  * a vectorised function that operates on a sequence or pandas Series
  * a streaming class with `update(...)` for bar-by-bar use

Streaming and vectorised forms must produce the same sequence of values for
the same inputs (tested in ``tests/test_indicators.py``). This lets strategies
use the streaming form in ``BaseStrategy.on_bar`` and lets backtest / research
code use the vectorised form on the same data with identical results.
"""

from talim.strategy.indicators.atr import AtrStream, atr_wilder
from talim.strategy.indicators.bollinger import BollingerStream, bollinger
from talim.strategy.indicators.donchian import DonchianStream, donchian
from talim.strategy.indicators.ema import EmaStream, ema
from talim.strategy.indicators.macd import MacdStream, macd
from talim.strategy.indicators.rsi import RsiStream, rsi_wilder
from talim.strategy.indicators.sma import SmaStream, sma
from talim.strategy.indicators.stochastic import StochasticStream, stochastic

__all__ = [
    "AtrStream",
    "atr_wilder",
    "BollingerStream",
    "bollinger",
    "DonchianStream",
    "donchian",
    "EmaStream",
    "ema",
    "MacdStream",
    "macd",
    "RsiStream",
    "rsi_wilder",
    "SmaStream",
    "sma",
    "StochasticStream",
    "stochastic",
]
