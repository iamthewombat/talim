"""strategy_update node (WP-14).

Asks the LLM to propose parameter changes for the active strategy given the
current regime context. Writes the proposal into `pending_notification` so
the notify node can format it for delivery.
"""

from __future__ import annotations

import json
import logging

from talim.app.llm_context import get_llm_client
from talim.app.state import TalimState
from talim.llm import prompts
from talim.llm.client import LLMUnavailable
from talim.strategy.store import StrategyStore

logger = logging.getLogger("talim.nodes.strategy_update")


def _parse_json_proposal(text: str) -> dict | None:
    """Best-effort JSON extraction from a model response."""
    text = text.strip()
    if not text:
        return None
    # Try direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to slicing the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def strategy_update(state: TalimState) -> TalimState:
    client = get_llm_client()
    if client is None:
        logger.warning("strategy_update: no LLM client configured")
        return {"regime_changed": False}

    active = state.get("active_strategies") or []
    if not active:
        store = StrategyStore()
        active = store.list_strategies()
    if not active:
        logger.info("strategy_update: no active strategies")
        return {"regime_changed": False}

    strategy_name = active[0]
    current_params = (state.get("strategy_params") or {}).get(strategy_name, {})
    regime = state.get("regime", "")

    prompt = prompts.strategy_reasoning_prompt(
        strategy_name=strategy_name,
        current_params=current_params,
        regime=regime,
    )

    try:
        response = client.reason(prompt)
    except LLMUnavailable as e:
        logger.warning("strategy_update: LLM unavailable: %s", e)
        return {"regime_changed": False}

    proposal = _parse_json_proposal(response.text) or {}
    rationale = proposal.pop("rationale", "")
    new_params = {**current_params, **proposal}

    merged = dict(state.get("strategy_params") or {})
    merged[strategy_name] = new_params

    # WP-25: persist proposal to git when explicitly enabled via env var.
    # Disabled by default so test runs don't mutate the working tree.
    import os
    if os.environ.get("TALIM_STRATEGY_GIT") == "1" and proposal:
        store = StrategyStore(git_enabled=True)
        try:
            current = store.read(strategy_name)
            store.write(
                strategy_name,
                current + f"\n\n<!-- {regime}: {proposal} -->\n",
            )
            store.commit_change(
                strategy_name,
                f"strategy_update: {strategy_name} regime={regime} {proposal}",
            )
        except FileNotFoundError:
            logger.debug(
                "strategy_update: %s markdown not found, skipping commit",
                strategy_name,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("strategy_update: commit_change failed: %s", e)

    notification = (
        f"Strategy update for {strategy_name} (regime={regime or 'unknown'}):\n"
        f"  proposed params: {proposal or '(no change)'}\n"
        f"  rationale: {rationale or '(none)'}"
    )

    return {
        "regime_changed": False,
        "strategy_params": merged,
        "pending_notification": notification,
    }
