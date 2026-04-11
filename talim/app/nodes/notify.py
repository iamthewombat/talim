"""notify node (WP-14).

Formats whatever's pending — a notification staged by another node, a
backtest result, or a user message — into a Discord-ready response. If an
LLM client is configured the result is polished by Claude; otherwise we
fall back to a deterministic template.
"""

from __future__ import annotations

import logging

from talim.app.llm_context import get_llm_client
from talim.app.state import TalimState
from talim.llm import prompts
from talim.llm.client import LLMUnavailable

logger = logging.getLogger("talim.nodes.notify")


def _format_backtest_results(results: list) -> str:
    lines = ["Backtest results:"]
    for r in results:
        lines.append(
            f"  - {r.strategy_name} params={r.param_variant} "
            f"sharpe={r.sharpe_ratio:.2f} net_pnl={r.net_pnl:.2f} "
            f"dd={r.max_drawdown:.2f} trades={r.total_trades}"
        )
    return "\n".join(lines)


def notify(state: TalimState) -> TalimState:
    client = get_llm_client()

    pending = state.get("pending_notification")
    backtest = state.get("backtest_result")
    user_msg = state.get("last_user_message")

    # Choose the best raw payload to format.
    if backtest:
        raw = _format_backtest_results(backtest)
        if client is not None:
            try:
                prompt = prompts.backtest_interpretation_prompt(
                    [r.to_dict() for r in backtest]
                )
                raw = client.reason(prompt).text or raw
            except LLMUnavailable as e:
                logger.warning("notify: LLM unavailable for backtest: %s", e)
    elif pending:
        raw = pending
    elif user_msg:
        if client is not None:
            try:
                raw = client.reason(
                    f"User asked: {user_msg!r}. Respond briefly."
                ).text or "ack"
            except LLMUnavailable as e:
                logger.warning("notify: LLM unavailable for user msg: %s", e)
                raw = "ack"
        else:
            raw = "ack"
    else:
        raw = "ack"

    return {
        "pending_notification": None,
        "last_user_message": None,
        "response_message": raw,
    }
