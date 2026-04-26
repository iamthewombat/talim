"""LangGraph SqliteSaver checkpointer factory."""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("talim.models.bar", "OHLCVBar"),
        ("talim.models.signal", "Signal"),
        ("talim.models.position", "Position"),
        ("talim.models.backtest", "BacktestRequest"),
        ("talim.models.backtest", "BacktestResult"),
    ]
)


def create_checkpointer(db_path: str = "talim_checkpoints.db") -> SqliteSaver:
    """Create a SqliteSaver for the graph.

    Use ':memory:' for in-memory (testing).
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn, serde=_SERDE)
    saver.setup()
    return saver
