"""Dependency injection container for the execute node (WP-23)."""

from __future__ import annotations

from talim.connectors.exchange.base import BaseExchange
from talim.memory.episodic import EpisodicMemory


class ExecuteContext:
    def __init__(self) -> None:
        self.exchange: BaseExchange | None = None
        self.episodic: EpisodicMemory | None = None
        self.default_qty: float = 1.0

    def configure(
        self,
        exchange: BaseExchange,
        episodic: EpisodicMemory | None = None,
        default_qty: float = 1.0,
    ) -> None:
        self.exchange = exchange
        self.episodic = episodic
        self.default_qty = default_qty

    def reset(self) -> None:
        self.exchange = None
        self.episodic = None
        self.default_qty = 1.0


_context = ExecuteContext()


def configure_execute(
    exchange: BaseExchange,
    episodic: EpisodicMemory | None = None,
    default_qty: float = 1.0,
) -> ExecuteContext:
    _context.configure(exchange, episodic, default_qty)
    return _context


def get_execute_context() -> ExecuteContext:
    return _context
