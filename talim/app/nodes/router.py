"""Router node — deterministic branch selection (WP-10).

The router is a no-op state pass-through. The actual branch decision lives in
`talim.app.edges.route_from_router`, which LangGraph invokes via a conditional
edge after the router node runs.
"""

from __future__ import annotations

import logging

from talim.app.state import TalimState

logger = logging.getLogger("talim.nodes.router")


def router(state: TalimState) -> TalimState:
    """No-op node. Branching is handled by the conditional edge."""
    logger.debug(
        "router: pending_signal=%s regime_changed=%s pending_backtest=%s last_user_message=%s",
        state.get("pending_signal") is not None,
        bool(state.get("regime_changed")),
        state.get("pending_backtest") is not None,
        state.get("last_user_message") is not None,
    )
    return {}
