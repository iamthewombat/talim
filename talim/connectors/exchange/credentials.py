"""Credential loader for exchange connectors.

Reads API keys from environment variables only — never from disk at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeCredentials:
    exchange: str
    api_key: str
    api_secret: str


def load_credentials(exchange: str) -> ExchangeCredentials:
    """Load API credentials for an exchange from env vars.

    Expects env vars named like:
        BINANCE_API_KEY, BINANCE_API_SECRET
        BYBIT_API_KEY, BYBIT_API_SECRET

    Raises KeyError if either variable is missing.
    """
    prefix = exchange.upper()
    key_var = f"{prefix}_API_KEY"
    secret_var = f"{prefix}_API_SECRET"

    api_key = os.environ.get(key_var)
    api_secret = os.environ.get(secret_var)

    if not api_key or not api_secret:
        missing = [v for v, val in [(key_var, api_key), (secret_var, api_secret)] if not val]
        raise KeyError(f"Missing required env vars for {exchange}: {missing}")

    return ExchangeCredentials(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
    )
