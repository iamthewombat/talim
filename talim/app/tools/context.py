"""Dependency container for tool wrappers (WP-27)."""

from __future__ import annotations

from dataclasses import dataclass

from talim.connectors.exchange.base import BaseExchange
from talim.llm.client import LLMClient
from talim.memory.episodic import EpisodicMemory


@dataclass
class ToolContext:
    """Bag of dependencies handed to each tool wrapper.

    Any field may be None — wrappers should raise a clear error if a
    required dependency is missing.
    """

    exchange: BaseExchange | None = None
    episodic: EpisodicMemory | None = None
    llm: LLMClient | None = None
