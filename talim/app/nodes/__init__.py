"""Stub implementations of all LangGraph nodes.

Each node logs its invocation and returns state unchanged. Real implementations
replace these stubs in subsequent work packages (WP-09 through WP-17).
"""

from __future__ import annotations

import logging

from talim.app.state import TalimState
from talim.models.position import Position
from talim.models.signal import Signal
from talim.app.nodes.signal_scanner import signal_scanner, configure_scanner  # noqa: F401
from talim.app.nodes.router import router  # noqa: F401
from talim.app.nodes.hitl_interrupt import hitl_interrupt, route_after_hitl  # noqa: F401
from talim.app.nodes.backtest_run import backtest_run  # noqa: F401
from talim.app.nodes.converse import converse  # noqa: F401
from talim.app.nodes.strategy_update import strategy_update  # noqa: F401
from talim.app.nodes.notify import notify  # noqa: F401
from talim.app.nodes.risk_check import risk_check, configure_risk_rules  # noqa: F401
from talim.app.nodes.position_monitor import position_monitor  # noqa: F401
from talim.app.nodes.reconcile import reconcile  # noqa: F401

logger = logging.getLogger("talim.nodes")


def _order_side_for_signal(signal: Signal) -> str:
    if signal.action == "exit":
        return "sell" if signal.side == "long" else "buy"
    return "buy" if signal.side == "long" else "sell"


def _matching_position(signal: Signal, positions: list[Position]) -> Position | None:
    for position in positions:
        if position.instrument == signal.instrument and position.side == signal.side:
            return position
    return None


def execute(state: TalimState) -> TalimState:
    """Submit approved order to the configured exchange (WP-23).

    Falls back to a no-op if no exchange has been wired (so unit tests that
    only exercise routing don't need to set one up).
    """
    from datetime import datetime, timezone
    from talim.app.execute_context import get_execute_context
    from talim.connectors.discord.position_events import (
        CloseoutEvent,
        OpenEvent,
        derive_reason,
        now_utc,
        post_closeout,
        post_open,
    )
    from talim.connectors.exchange.base import OrderStatus
    from talim.metrics import METRICS

    sig = state.get("pending_signal")
    update: TalimState = {"pending_signal": None}
    if sig is None:
        return update

    ctx = get_execute_context()
    if ctx.exchange is None:
        logger.info("execute: no exchange configured, skipping order placement")
        update["last_action"] = (
            f"would-execute {sig.action} {sig.side} {sig.instrument} ({sig.strategy})"
        )
        return update

    closing_position = None
    realised_pnl = 0.0
    try:
        if sig.action == "exit":
            position = _matching_position(sig, list(state.get("active_positions") or []))
            if position is None:
                position = _matching_position(sig, ctx.exchange.get_positions())
            if position is None:
                update["last_action"] = (
                    f"execute-skipped exit {sig.side} {sig.instrument}: "
                    "no matching open position"
                )
                return update
            closing_position = position
            order = ctx.exchange.close_position(position, strategy=sig.strategy)
        else:
            order = ctx.exchange.place_order(
                instrument=sig.instrument,
                side=_order_side_for_signal(sig),
                qty=ctx.default_qty,
                strategy=sig.strategy,
                stop_price=sig.stop if sig.stop > 0 else None,
                target_price=sig.target if sig.target > 0 else None,
            )
        METRICS.inc("talim_orders_placed_total")
        logger.info(
            "execute: placed order %s status=%s", order.order_id, order.status.value
        )
        if order.status == OrderStatus.REJECTED:
            update["last_action"] = (
                f"execute-rejected {sig.action} {sig.side} "
                f"{sig.instrument} ({sig.strategy})"
            )
        else:
            update["last_action"] = (
                f"executed {sig.action} {sig.side} {sig.instrument} ({sig.strategy})"
            )
            try:
                update["active_positions"] = ctx.exchange.get_positions()
            except Exception:  # noqa: BLE001
                logger.warning("execute: failed to refresh positions", exc_info=True)
            if sig.action == "exit" and closing_position is not None:
                exit_price = order.fill_price
                pnl = None
                if isinstance(exit_price, (int, float)):
                    direction = 1.0 if closing_position.side == "long" else -1.0
                    pnl = (
                        (exit_price - closing_position.entry_price)
                        * direction
                        * closing_position.qty
                    )
                    realised_pnl = float(pnl)
                try:
                    post_closeout(
                        CloseoutEvent(
                            instrument=closing_position.instrument,
                            side=closing_position.side,
                            strategy=sig.strategy or closing_position.strategy,
                            qty=closing_position.qty,
                            entry_price=closing_position.entry_price,
                            exit_price=exit_price,
                            pnl=pnl,
                            entry_time=closing_position.entry_time,
                            exit_time=order.fill_time or now_utc(),
                            order_id=order.order_id,
                            reason=derive_reason(
                                exit_price=exit_price,
                                stop=closing_position.stop,
                                target=closing_position.target,
                                side=closing_position.side,
                            ),
                        )
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("execute: close-out webhook push failed", exc_info=True)
            elif sig.action != "exit":
                atr_current = state.get("atr_current")
                try:
                    post_open(
                        OpenEvent(
                            instrument=sig.instrument,
                            side=sig.side,
                            strategy=sig.strategy,
                            qty=order.qty,
                            entry_price=order.fill_price if isinstance(order.fill_price, (int, float)) else sig.entry_price,
                            stop=sig.stop,
                            target=sig.target,
                            regime=sig.regime_context,
                            atr=atr_current if isinstance(atr_current, (int, float)) else None,
                            entry_time=order.fill_time or now_utc(),
                            order_id=order.order_id,
                        )
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("execute: open webhook push failed", exc_info=True)
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
                outcome="closed" if sig.action == "exit" else "pending",
                approved=True,
                signal_type=sig.action,
                pnl=realised_pnl,
                atr_ratio=state.get("atr_ratio"),
                action="approve",
                notes=f"order_id={order.order_id} order_side={order.side} qty={order.qty}",
            )
            if (
                sig.action == "exit"
                and order.status != OrderStatus.REJECTED
            ):
                ctx.episodic.close_pending_entries(
                    instrument=sig.instrument,
                    side=sig.side,
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
    "position_monitor",
    "reconcile",
]
