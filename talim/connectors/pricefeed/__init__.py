"""Price feed connectors — base ABC, Binance WS, mock replay, normaliser."""

from talim.connectors.pricefeed.base import BasePriceFeed, BarCallback
from talim.connectors.pricefeed.factory import create_pricefeed, PriceFeedConfigError
from talim.connectors.pricefeed.ig import IgPriceFeed
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.connectors.pricefeed.normaliser import (
    PriceSnapshot,
    SnapshotBarBuilder,
    normalise_binance_kline,
    normalise_ig_price_bar,
    normalise_ig_snapshot,
)

__all__ = [
    "BasePriceFeed",
    "BarCallback",
    "create_pricefeed",
    "PriceFeedConfigError",
    "IgPriceFeed",
    "MockPriceFeed",
    "PriceSnapshot",
    "SnapshotBarBuilder",
    "normalise_binance_kline",
    "normalise_ig_price_bar",
    "normalise_ig_snapshot",
]
