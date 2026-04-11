"""converse node (WP-14).

Parses an incoming user message: identifies referenced strategies, classifies
the intent (question / command / backtest / other), and loads relevant
strategy markdown into state for downstream nodes to use.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from talim.app.llm_context import get_llm_client
from talim.app.state import TalimState
from talim.llm import prompts
from talim.llm.client import LLMUnavailable
from talim.strategy.store import StrategyStore

logger = logging.getLogger("talim.nodes.converse")


def _find_strategy_references(message: str, known: list[str]) -> list[str]:
    msg_lower = message.lower()
    return [s for s in known if s.lower() in msg_lower]


def converse(state: TalimState) -> TalimState:
    message = state.get("last_user_message") or ""
    if not message:
        return {}

    store = StrategyStore()
    known = store.list_strategies()
    referenced = _find_strategy_references(message, known)

    # Activate referenced strategies (additive — don't drop existing).
    active = list(state.get("active_strategies") or [])
    for s in referenced:
        if s not in active:
            active.append(s)

    update: dict = {}
    if active:
        update["active_strategies"] = active

    # Append the inbound message to the rolling chat history (architecture §3).
    history = list(state.get("messages") or [])
    history.append({
        "role": "user",
        "content": message,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    })
    update["messages"] = history

    # Optional LLM classification — used by downstream notify if available.
    client = get_llm_client()
    if client is not None:
        try:
            res = client.classify(prompts.message_classification_prompt(message))
            label = (res.text or "").strip().upper()
            logger.info("converse: classified message as %s", label)
        except LLMUnavailable as e:
            logger.debug("converse: classifier unavailable: %s", e)

    return update
