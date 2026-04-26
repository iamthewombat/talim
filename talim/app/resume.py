"""Resume a graph that has paused at the HITL interrupt (WP-11)."""

from __future__ import annotations

import logging

from talim.app.graph import build_graph
from talim.app.checkpointer import create_checkpointer

logger = logging.getLogger("talim.app.resume")


def resume_graph(
    thread_id: str,
    approved: bool,
    db_path: str = "./talim.db",
    checkpointer=None,
):
    """Resume a HITL-paused graph with the user's decision.

    Args:
        thread_id: The thread the graph was running under.
        approved: True to route to `execute`, False to route to `notify` (rejection).
        db_path: SQLite checkpoint file path used when `checkpointer` is not supplied.
        checkpointer: Optional shared SqliteSaver used by the live runtime.

    Returns:
        Final state dict after the graph runs to completion.
    """
    cp = checkpointer or create_checkpointer(db_path)
    graph = build_graph(checkpointer=cp)
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    if snapshot is None:
        raise ValueError(f"No checkpoint found for thread {thread_id!r}")

    # Inject the human's decision, then continue from the interrupt point.
    update = {"signal_approved": bool(approved)}
    if not approved:
        # On rejection, clear the pending signal so it isn't picked up again.
        update["pending_signal"] = None
    graph.update_state(config, update)
    logger.info("resume_graph: thread=%s approved=%s", thread_id, approved)
    return graph.invoke(None, config=config)
