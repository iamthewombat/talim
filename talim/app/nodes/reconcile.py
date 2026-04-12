"""Order reconciliation node — detects drift between exchange and memory (WP-35).

Runs periodically (via cron or scheduler). Pulls live positions from the
exchange, compares against episodic memory's pending/open decisions, and
emits repair events for any divergences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from talim.app.execute_context import get_execute_context
from talim.app.state import TalimState
from talim.connectors.exchange.base import BaseExchange
from talim.memory.episodic import EpisodicMemory
from talim.models.position import Position

logger = logging.getLogger("talim.nodes.reconcile")


@dataclass
class RepairEvent:
    """Describes a divergence between exchange and memory."""

    kind: str  # "missing_in_memory" | "missing_on_exchange" | "qty_mismatch" | "side_mismatch"
    instrument: str
    detail: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "instrument": self.instrument,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


def reconcile_positions(
    exchange: BaseExchange,
    episodic: EpisodicMemory,
    state_positions: list[Position] | None = None,
) -> list[RepairEvent]:
    """Compare exchange positions against episodic memory and state.

    Returns a list of RepairEvent for every divergence found.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    repairs: list[RepairEvent] = []

    # 1. Get what the exchange says is open
    exchange_positions = {p.instrument: p for p in exchange.get_positions()}

    # 2. Get pending decisions from episodic memory (outcome = "pending")
    pending = episodic.query_decisions()
    memory_pending: dict[str, dict] = {}
    for d in pending:
        if d.get("outcome") == "pending":
            memory_pending[d["instrument"]] = d

    # 3. State positions (what the graph thinks is open)
    state_map: dict[str, Position] = {}
    for p in (state_positions or []):
        state_map[p.instrument] = p

    # All instruments across all three sources
    all_instruments = set(exchange_positions) | set(memory_pending) | set(state_map)

    for inst in sorted(all_instruments):
        ex_pos = exchange_positions.get(inst)
        mem = memory_pending.get(inst)
        st_pos = state_map.get(inst)

        # Exchange has a position but memory has no pending record
        if ex_pos is not None and mem is None:
            repairs.append(RepairEvent(
                kind="missing_in_memory",
                instrument=inst,
                detail=f"exchange has {ex_pos.side} {ex_pos.qty} but no pending decision in memory",
                timestamp=now,
            ))

        # Memory has a pending decision but exchange has no position
        if mem is not None and ex_pos is None:
            repairs.append(RepairEvent(
                kind="missing_on_exchange",
                instrument=inst,
                detail=f"memory has pending {mem['side']} decision but no exchange position",
                timestamp=now,
            ))

        # Both exist — check for mismatches
        if ex_pos is not None and mem is not None:
            if ex_pos.side != mem["side"]:
                repairs.append(RepairEvent(
                    kind="side_mismatch",
                    instrument=inst,
                    detail=f"exchange side={ex_pos.side} but memory side={mem['side']}",
                    timestamp=now,
                ))

        # State vs exchange mismatch
        if ex_pos is not None and st_pos is not None:
            if abs(ex_pos.qty - st_pos.qty) > 1e-9:
                repairs.append(RepairEvent(
                    kind="qty_mismatch",
                    instrument=inst,
                    detail=f"exchange qty={ex_pos.qty} but state qty={st_pos.qty}",
                    timestamp=now,
                ))

    return repairs


def reconcile(state: TalimState) -> TalimState:
    """LangGraph node that runs reconciliation and surfaces divergences.

    If divergences are found, they are written to `pending_notification`
    so the notify node can surface them (e.g. via Discord).
    """
    update: TalimState = {}  # type: ignore[assignment]

    ctx = get_execute_context()
    if ctx.exchange is None or ctx.episodic is None:
        logger.info("reconcile: exchange or episodic not configured, skipping")
        return update

    repairs = reconcile_positions(
        exchange=ctx.exchange,
        episodic=ctx.episodic,
        state_positions=state.get("active_positions"),
    )

    if not repairs:
        logger.info("reconcile: no divergences found")
        return update

    lines = [f"Reconciliation found {len(repairs)} divergence(s):"]
    for r in repairs:
        lines.append(f"  [{r.kind}] {r.instrument}: {r.detail}")
    msg = "\n".join(lines)

    logger.warning(msg)
    update["pending_notification"] = msg
    return update
