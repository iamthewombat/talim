"""Price-feed factory for local/test/live wiring."""

from __future__ import annotations

import logging
import os

from talim.connectors.pricefeed.base import BasePriceFeed

logger = logging.getLogger("talim.pricefeed.factory")

VALID_FEEDS = {"mock", "binance", "ig", "forexcom"}


class PriceFeedConfigError(ValueError):
    """Raised when price-feed configuration is invalid."""


def create_pricefeed(
    feed_name: str | None = None,
    *,
    timeframe: str | None = None,
) -> BasePriceFeed:
    name = (feed_name or os.environ.get("TALIM_PRICEFEED", "mock")).strip().lower()
    timeframe = timeframe or os.environ.get("TALIM_PRICEFEED_TIMEFRAME", "5m")
    if name not in VALID_FEEDS:
        raise PriceFeedConfigError(
            f"invalid TALIM_PRICEFEED={name!r}; must be one of {sorted(VALID_FEEDS)}"
        )

    if name == "mock":
        from talim.connectors.pricefeed.mock import MockPriceFeed

        logger.info("pricefeed factory: using MockPriceFeed(timeframe=%s)", timeframe)
        return MockPriceFeed(timeframe=timeframe)

    if name == "binance":
        from talim.connectors.pricefeed.binance import BinancePriceFeed

        logger.info("pricefeed factory: using BinancePriceFeed(timeframe=%s)", timeframe)
        return BinancePriceFeed(timeframe=timeframe)

    if name == "ig":
        from talim.connectors.pricefeed.ig import IgPriceFeed

        logger.info("pricefeed factory: using IgPriceFeed(timeframe=%s)", timeframe)
        return IgPriceFeed.from_env(timeframe=timeframe)

    from talim.connectors.pricefeed.forexcom import ForexcomPriceFeed

    logger.info("pricefeed factory: using ForexcomPriceFeed(timeframe=%s)", timeframe)
    return ForexcomPriceFeed.from_env(timeframe=timeframe)
