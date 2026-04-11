"""HITL interrupt node (WP-11).

Formats the pending signal into a notification ready for Discord/bridge,
then the graph pauses (via `interrupt_after=["hitl_interrupt"]` configured at
compile time) until a human resumes it via `talim.app.resume.resume_graph`.
"""

from __future__ import annotations

import logging

from talim.app.state import TalimState

logger = logging.getLogger("talim.nodes.hitl_interrupt")


def format_signal_message(state: TalimState) -> str:
    sig = state.get("pending_signal")
    if sig is None:
        return "(no pending signal)"
    regime = sig.regime_context or state.get("regime", "?")
    atr = state.get("atr_current")
    atr_str = f"{atr:.2f}" if isinstance(atr, (int, float)) else "?"
    risk = abs(sig.entry_price - sig.stop)
    reward = abs(sig.target - sig.entry_price)
    rr = (reward / risk) if risk > 0 else 0.0
    return (
        f"[{sig.strategy}] {sig.side.upper()} {sig.instrument} @ {sig.entry_price:.2f}\n"
        f"  stop={sig.stop:.2f}  target={sig.target:.2f}  R:R={rr:.2f}\n"
        f"  regime={regime}  ATR={atr_str}\n"
        f"  rationale: {sig.rationale}\n"
        f"  React ✅ to approve, ❌ to reject."
    )


def hitl_interrupt(state: TalimState) -> TalimState:
    """Format the pending signal and stage it for human review.

    Returns a state update with `pending_notification` set. The graph is
    compiled with `interrupt_after=["hitl_interrupt"]` so execution pauses
    here until `resume_graph` is called.
    """
    sig = state.get("pending_signal")
    if sig is None:
        logger.warning("hitl_interrupt: no pending_signal — nothing to review")
        return {"signal_approved": False}

    message = format_signal_message(state)
    logger.info("hitl_interrupt: awaiting approval for %s %s", sig.strategy, sig.side)
    return {"pending_notification": message}


def route_after_hitl(state: TalimState) -> str:
    """Conditional edge after the human resumes."""
    if state.get("signal_approved") is True:
        return "execute"
    return "notify"
