"""Conditional edge functions for the Talim LangGraph (WP-10).

Routing rules (deterministic, no LLM):

    pending_signal is not None       → "risk_check"
    regime_changed is True           → "strategy_update"
    pending_backtest is not None     → "backtest_run"
    last_user_message is not None    → "notify"
    otherwise                        → "end"

Priority order matters: a pending_signal always wins over a regime change so
that an in-flight trade is never delayed by a parameter rebuild.
"""

from __future__ import annotations

from talim.app.state import TalimState


ROUTER_BRANCHES = ("risk_check", "strategy_update", "backtest_run", "notify", "end")


def route_from_router(state: TalimState) -> str:
    """Pick the next node after the router based on state contents."""
    if state.get("pending_signal") is not None:
        return "risk_check"
    if state.get("regime_changed"):
        return "strategy_update"
    if state.get("pending_backtest") is not None:
        return "backtest_run"
    if state.get("last_user_message") is not None:
        return "notify"
    return "end"
