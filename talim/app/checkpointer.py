"""LangGraph SqliteSaver checkpointer factory."""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver


def create_checkpointer(db_path: str = "talim_checkpoints.db") -> SqliteSaver:
    """Create a SqliteSaver for the graph.

    Use ':memory:' for in-memory (testing).
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
