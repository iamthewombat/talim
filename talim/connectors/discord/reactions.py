"""Reaction handling for HITL approval (WP-15)."""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger("talim.discord.reactions")


APPROVE_EMOJI = "✅"
REJECT_EMOJI = "❌"


def interpret_reaction(emoji: str) -> Optional[bool]:
    """Map a reaction emoji to a HITL decision.

    Returns True for approve, False for reject, None for any other emoji.
    """
    if emoji == APPROVE_EMOJI:
        return True
    if emoji == REJECT_EMOJI:
        return False
    return None


class ReactionHandler:
    """Tracks alert message ids → thread ids and dispatches HITL resumes.

    Usage:
        handler = ReactionHandler(resume_callback=resume_graph)
        handler.register(message_id=123, thread_id="cron-1")
        handler.handle_reaction(message_id=123, emoji="✅")
        # → resume_graph("cron-1", approved=True) is called
    """

    def __init__(self, resume_callback: Callable[[str, bool], None]) -> None:
        self._resume = resume_callback
        self._messages: dict[int, str] = {}

    def register(self, message_id: int, thread_id: str) -> None:
        self._messages[message_id] = thread_id

    def get_thread(self, message_id: int) -> str | None:
        return self._messages.get(message_id)

    def handle_reaction(self, message_id: int, emoji: str) -> bool:
        """Process a reaction. Returns True if it triggered a resume."""
        decision = interpret_reaction(emoji)
        if decision is None:
            return False
        thread_id = self._messages.pop(message_id, None)
        if thread_id is None:
            logger.warning("reaction on unknown message id=%s", message_id)
            return False
        logger.info(
            "reaction: message=%s thread=%s approved=%s",
            message_id, thread_id, decision,
        )
        self._resume(thread_id, decision)
        return True
