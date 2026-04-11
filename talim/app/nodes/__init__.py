"""Stub implementations of all LangGraph nodes.

Each node logs its invocation and returns state unchanged. Real implementations
replace these stubs in subsequent work packages (WP-09 through WP-17).
"""

from __future__ import annotations

import logging

from talim.app.state import TalimState
from talim.app.nodes.signal_scanner import signal_scanner, configure_scanner  # noqa: F401
from talim.app.nodes.router import router  # noqa: F401
from talim.app.nodes.hitl_interrupt import hitl_interrupt, route_after_hitl  # noqa: F401
from talim.app.nodes.backtest_run import backtest_run  # noqa: F401
from talim.app.nodes.converse import converse  # noqa: F401
from talim.app.nodes.strategy_update import strategy_update  # noqa: F401
from talim.app.nodes.notify import notify  # noqa: F401
from talim.app.nodes.risk_check import risk_check, configure_risk_rules  # noqa: F401

logger = logging.getLogger("talim.nodes")


def execute(state: TalimState) -> TalimState:
    """Submit approved order to the configured exchange (WP-23).

    Falls back to a no-op if no exchange has been wired (so unit tests that
    only exercise routing don't need to set one up).
    """
    from datetime import datetime, timezone
    from talim.app.execute_context import get_execute_context

    sig = state.get("pending_signal")
    update: TalimState = {"pending_signal": None}
    if sig is None:
        return update

    ctx = get_execute_context()
    if ctx.exchange is None:
        logger.info("execute: no exchange configured, skipping order placement")
        update["last_action"] = (
            f"would-execute {sig.side} {sig.instrument} ({sig.strategy})"
        )
        return update

    try:
        order = ctx.exchange.place_order(
            instrument=sig.instrument,
            side=("buy" if sig.side == "long" else "sell"),
            qty=ctx.default_qty,
            strategy=sig.strategy,
        )
        logger.info(
            "execute: placed order %s status=%s", order.order_id, order.status.value
        )
        update["last_action"] = (
            f"executed {sig.action} {sig.side} {sig.instrument} ({sig.strategy})"
        )
        if ctx.episodic is not None:
            ctx.episodic.record_decision(
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                instrument=sig.instrument,
                strategy=sig.strategy,
                side=sig.side,
                entry_price=sig.entry_price,
                stop=sig.stop,
                target=sig.target,
                regime=sig.regime_context,
                rationale=sig.rationale,
                outcome="pending",
                approved=True,
                signal_type=sig.action,
                atr_ratio=state.get("atr_ratio"),
                action="approve",
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("execute: order placement failed: %s", e)
        update["last_action"] = f"execute-failed: {e}"

    return update


__all__ = [
    "signal_scanner",
    "configure_scanner",
    "converse",
    "router",
    "risk_check",
    "hitl_interrupt",
    "execute",
    "strategy_update",
    "backtest_run",
    "notify",
]
