"""Exchange factory — selects mock/testnet/live based on config (WP-32/WP-50).

Usage at startup:

    exchange = create_exchange()  # reads TALIM_EXCHANGE_MODE from env

Modes:
    mock     — MockExchange (default, no credentials needed)
    testnet  — CcxtExchange sandbox or IG demo
    live     — CcxtExchange production or IG live
"""

from __future__ import annotations

import logging
import os

from talim.connectors.exchange.base import BaseExchange

logger = logging.getLogger("talim.exchange.factory")

VALID_MODES = {"mock", "testnet", "live"}


class ExchangeConfigError(ValueError):
    """Raised when exchange configuration is invalid or incomplete."""


def create_exchange(
    mode: str | None = None,
    exchange_name: str | None = None,
    starting_balance: float = 100_000.0,
) -> BaseExchange:
    """Create an exchange instance based on the configured mode.

    Args:
        mode: "mock", "testnet", or "live". Defaults to TALIM_EXCHANGE_MODE env
              (falls back to "mock").
        exchange_name: ccxt exchange id (e.g. "binance", "bybit"). Defaults to
                       TALIM_EXCHANGE_NAME env. Required for testnet/live.
        starting_balance: Initial balance for MockExchange (ignored otherwise).
    """
    mode = mode or os.environ.get("TALIM_EXCHANGE_MODE", "mock")
    if mode not in VALID_MODES:
        raise ExchangeConfigError(
            f"invalid TALIM_EXCHANGE_MODE={mode!r}; must be one of {sorted(VALID_MODES)}"
        )

    if mode == "mock":
        from talim.connectors.exchange.mock_exchange import MockExchange
        logger.info("exchange factory: using MockExchange (balance=%.0f)", starting_balance)
        return MockExchange(starting_balance=starting_balance)

    # testnet or live — need real credentials
    exchange_name = exchange_name or os.environ.get("TALIM_EXCHANGE_NAME")
    if not exchange_name:
        raise ExchangeConfigError(
            f"TALIM_EXCHANGE_NAME required for mode={mode}"
        )

    if exchange_name.lower() == "ig":
        try:
            from talim.connectors.exchange.ig_exchange import IgExchange
            environment = "demo" if mode == "testnet" else "live"
            logger.info("exchange factory: using IgExchange(environment=%s)", environment)
            return IgExchange.from_env(environment=environment)
        except (ValueError, RuntimeError) as e:
            raise ExchangeConfigError(str(e)) from e

    if exchange_name.lower() == "forexcom":
        try:
            from talim.connectors.exchange.forexcom_exchange import ForexcomExchange
            logger.info("exchange factory: using ForexcomExchange (single-host)")
            return ForexcomExchange.from_env()
        except (ValueError, RuntimeError) as e:
            raise ExchangeConfigError(str(e)) from e

    from talim.security.vault import Vault, VaultError

    try:
        vault = Vault.load_from_env([exchange_name])
    except VaultError as e:
        raise ExchangeConfigError(str(e)) from e

    from talim.connectors.exchange.ccxt_exchange import CcxtExchange

    sandbox = mode == "testnet"
    logger.info(
        "exchange factory: using CcxtExchange(%s, sandbox=%s)",
        exchange_name,
        sandbox,
    )
    return CcxtExchange.from_vault(exchange_name, vault, sandbox=sandbox)
