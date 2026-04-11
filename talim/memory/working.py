"""Working memory — validates LangGraph's SqliteSaver works with TalimState.

This module is primarily a validation/test wrapper. LangGraph's SqliteSaver
handles the actual checkpointing; we just confirm TalimState round-trips
correctly.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator

from langgraph.checkpoint.sqlite import SqliteSaver


def create_checkpointer(db_path: str = "talim_checkpoints.db") -> SqliteSaver:
    """Create a SqliteSaver checkpointer for LangGraph.

    Args:
        db_path: Path to the SQLite database file.
               Use \":memory:\" for in-memory (testing).

    Returns:
        A configured SqliteSaver instance.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
