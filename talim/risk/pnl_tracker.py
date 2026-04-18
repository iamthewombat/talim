"""P&L tracker — refreshes open/daily PnL from exchange state (WP-36).

Provides a single source of truth for P&L rather than relying on
opportunistic updates from the execute node.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

from talim.cfd import CfdInstrumentRegistry, load_default_registry
from talim.connectors.exchange.base import BaseExchange
from talim.risk.cfd import (
    DEFAULT_CFD_FINANCING_ANNUAL_RATE,
    estimate_financing_cost,
    exposure_for_position,
    select_account_balance,
)

logger = logging.getLogger("talim.risk.pnl_tracker")


@dataclass
class PnLSnapshot:
    """Point-in-time P&L reading."""

    open_pnl: float
    daily_pnl: float
    account_balance: float
    position_count: int
    timestamp: str
    gross_open_pnl: float = 0.0
    financing_cost: float = 0.0
    account_currency: str = ""
    margin_in_use: float = 0.0

    def to_dict(self) -> dict:
        return {
            "open_pnl": self.open_pnl,
            "daily_pnl": self.daily_pnl,
            "account_balance": self.account_balance,
            "position_count": self.position_count,
            "timestamp": self.timestamp,
            "gross_open_pnl": self.gross_open_pnl,
            "financing_cost": self.financing_cost,
            "account_currency": self.account_currency,
            "margin_in_use": self.margin_in_use,
        }


class PnLTracker:
    """Tracks P&L across session boundaries.

    Call `refresh` on each tick/schedule to update from exchange.
    Call `reset_daily` at session rollover to zero out daily_pnl.
    """

    def __init__(
        self,
        session_tz: tzinfo | None = None,
        *,
        registry: CfdInstrumentRegistry | None = None,
        financing_annual_rate: float = DEFAULT_CFD_FINANCING_ANNUAL_RATE,
    ) -> None:
        self._session_tz = session_tz or timezone.utc
        self._session_date: str | None = None
        self._daily_pnl: float = 0.0
        self._last_balance: float | None = None
        self._registry = registry or load_default_registry()
        self._financing_annual_rate = financing_annual_rate

    def refresh(self, exchange: BaseExchange, now: datetime | None = None) -> PnLSnapshot:
        """Pull current state from exchange and compute P&L."""
        current = now or datetime.now(tz=self._session_tz)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(self._session_tz)
        today = current.date().isoformat()

        # Session rollover
        if self._session_date is not None and today != self._session_date:
            logger.info("pnl_tracker: session rollover %s → %s", self._session_date, today)
            self._daily_pnl = 0.0
        self._session_date = today

        balance = exchange.get_account_balance()
        positions = exchange.get_positions()
        account_currency, account_balance = select_account_balance(
            balance,
            positions,
            registry=self._registry,
        )

        gross_open_pnl = sum(p.open_pnl for p in positions)
        financing_cost = sum(
            estimate_financing_cost(
                position,
                annual_rate=self._financing_annual_rate,
                at=current,
                registry=self._registry,
            )
            for position in positions
        )
        margin_in_use = sum(
            snapshot.required_margin
            for position in positions
            if (snapshot := exposure_for_position(position, registry=self._registry)) is not None
        )
        open_pnl = gross_open_pnl - financing_cost

        # Daily P&L: track change in account balance since first refresh of the day
        if self._last_balance is not None:
            delta = account_balance - self._last_balance
            self._daily_pnl += delta
        self._last_balance = account_balance

        return PnLSnapshot(
            open_pnl=open_pnl,
            daily_pnl=self._daily_pnl,
            account_balance=account_balance,
            position_count=len(positions),
            timestamp=current.isoformat(),
            gross_open_pnl=gross_open_pnl,
            financing_cost=financing_cost,
            account_currency=account_currency,
            margin_in_use=margin_in_use,
        )

    def reset_daily(self) -> None:
        """Manually reset daily P&L (e.g. at session open)."""
        self._daily_pnl = 0.0
        self._last_balance = None
