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

from talim.app.hitl_mode import is_hitl_enabled
from talim.app.state import TalimState


ROUTER_BRANCHES = ("risk_check", "strategy_update", "backtest_run", "notify", "end")
RISK_BRANCHES = ("execute", "hitl_interrupt", "notify", "end")


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


def route_after_risk(state: TalimState) -> str:
    """Pick the next node after risk_check.

    Entry signals still require HITL. Protective exit signals are already part
    of the approved trade plan, so they must continue directly to execution;
    pausing them for another approval turns a stop into a suggestion.
    """
    sig = state.get("pending_signal")
    if sig is None:
        return "notify" if state.get("pending_notification") is not None else "end"
    if getattr(sig, "action", "enter") == "exit":
        return "execute"
    if not is_hitl_enabled():
        return "execute"
    return "hitl_interrupt"
