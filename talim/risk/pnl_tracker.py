"""P&L tracker — refreshes open/daily PnL from exchange state (WP-36).

Provides a single source of truth for P&L rather than relying on
opportunistic updates from the execute node.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

from talim.connectors.exchange.base import BaseExchange

logger = logging.getLogger("talim.risk.pnl_tracker")


@dataclass
class PnLSnapshot:
    """Point-in-time P&L reading."""

    open_pnl: float
    daily_pnl: float
    account_balance: float
    position_count: int
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "open_pnl": self.open_pnl,
            "daily_pnl": self.daily_pnl,
            "account_balance": self.account_balance,
            "position_count": self.position_count,
            "timestamp": self.timestamp,
        }


class PnLTracker:
    """Tracks P&L across session boundaries.

    Call `refresh` on each tick/schedule to update from exchange.
    Call `reset_daily` at session rollover to zero out daily_pnl.
    """

    def __init__(self, session_tz: tzinfo | None = None) -> None:
        self._session_tz = session_tz or timezone.utc
        self._session_date: str | None = None
        self._daily_pnl: float = 0.0
        self._last_balance: float | None = None

    def refresh(self, exchange: BaseExchange) -> PnLSnapshot:
        """Pull current state from exchange and compute P&L."""
        now = datetime.now(tz=self._session_tz)
        today = now.date().isoformat()

        # Session rollover
        if self._session_date is not None and today != self._session_date:
            logger.info("pnl_tracker: session rollover %s → %s", self._session_date, today)
            self._daily_pnl = 0.0
        self._session_date = today

        balance = exchange.get_account_balance()
        account_balance = balance.get("USD", 0.0)

        positions = exchange.get_positions()
        open_pnl = sum(p.open_pnl for p in positions)

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
            timestamp=now.isoformat(),
        )

    def reset_daily(self) -> None:
        """Manually reset daily P&L (e.g. at session open)."""
        self._daily_pnl = 0.0
        self._last_balance = None
