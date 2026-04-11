"""Entry points — cron_trigger and bridge_message."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from talim.app.graph import build_graph
from talim.app.state import TalimState


def _default_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def cron_trigger(
    initial_state: TalimState | None = None,
    thread_id: str = "cron-main",
    checkpointer=None,
) -> TalimState:
    """Invoke the graph on the cron path (signal scanner → router → ...).

    Args:
        initial_state: Optional seed state. A minimal state is constructed if None.
        thread_id: LangGraph thread id for checkpointing.
        checkpointer: Optional SqliteSaver.

    Returns:
        The final state after graph execution.
    """
    graph = build_graph(checkpointer=checkpointer)

    state: TalimState = dict(initial_state) if initial_state else {}  # type: ignore[assignment]
    state.setdefault("thread_id", thread_id)
    state.setdefault("last_scan_time", datetime.now(tz=timezone.utc).isoformat())
    # Ensure bridge path is not taken accidentally
    state.setdefault("last_user_message", None)

    final = graph.invoke(state, config=_default_config(thread_id))
    return final  # type: ignore[return-value]


def bridge_message(
    message: str,
    initial_state: TalimState | None = None,
    thread_id: str = "bridge-main",
    checkpointer=None,
) -> TalimState:
    """Invoke the graph on the bridge path (converse → router → notify).

    Args:
        message: The user's incoming message.
        initial_state: Optional seed state.
        thread_id: LangGraph thread id for checkpointing.
        checkpointer: Optional SqliteSaver.

    Returns:
        The final state after graph execution.
    """
    graph = build_graph(checkpointer=checkpointer)

    state: TalimState = dict(initial_state) if initial_state else {}  # type: ignore[assignment]
    state.setdefault("thread_id", thread_id)
    state["last_user_message"] = message

    final = graph.invoke(state, config=_default_config(thread_id))
    return final  # type: ignore[return-value]
