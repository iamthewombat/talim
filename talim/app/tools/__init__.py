"""MCP-style tool wrappers (WP-27).

Each function takes a `ToolContext` (a thin container of dependencies that
mirrors the rest of Talim's DI pattern) and returns a JSON-serialisable dict.
The wrappers are deliberately small so the MCP server in `server.py` can
register them as-is.
"""

from talim.app.tools.context import ToolContext
from talim.app.tools.wrappers import (
    get_positions,
    get_pnl,
    run_backtest,
    propose_strategy_update,
    query_episodic_memory,
    TOOLS,
)

__all__ = [
    "ToolContext",
    "get_positions",
    "get_pnl",
    "run_backtest",
    "propose_strategy_update",
    "query_episodic_memory",
    "TOOLS",
]
