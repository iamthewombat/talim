"""LangGraph StateGraph definition for Talim.

Topology:

    cron_trigger ──▶ signal_scanner ──▶ router ──┬──▶ risk_check ──┬──▶ hitl_interrupt ──▶ execute ──▶ END
                                                  │                 └──▶ execute ──▶ END  (protective exits)
                                                  ├──▶ strategy_update ──▶ notify ──▶ END
                                                  ├──▶ backtest_run ──▶ notify ──▶ END
                                                  ├──▶ notify ──▶ END
                                                  └──▶ END

    bridge_message ──▶ converse ──▶ router ──▶ (same branches as above)
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from talim.app.state import TalimState
from talim.app import nodes
from talim.app.edges import route_after_risk, route_from_router  # re-exported for back-compat

__all__ = ["build_graph", "route_from_router", "route_after_risk"]


def build_graph(checkpointer=None):
    """Build and compile the Talim LangGraph StateGraph.

    Args:
        checkpointer: Optional SqliteSaver for persistence.

    Returns:
        A compiled graph ready to invoke.
    """
    graph = StateGraph(TalimState)

    # Register nodes
    graph.add_node("signal_scanner", nodes.signal_scanner)
    graph.add_node("position_monitor", nodes.position_monitor)
    graph.add_node("converse", nodes.converse)
    graph.add_node("router", nodes.router)
    graph.add_node("risk_check", nodes.risk_check)
    graph.add_node("hitl_interrupt", nodes.hitl_interrupt)
    graph.add_node("execute", nodes.execute)
    graph.add_node("strategy_update", nodes.strategy_update)
    graph.add_node("backtest_run", nodes.backtest_run)
    graph.add_node("notify", nodes.notify)

    # Entry points — we use conditional edges at START to pick cron vs bridge
    def pick_entry(state: TalimState) -> str:
        if state.get("last_user_message") is not None:
            return "converse"
        return "signal_scanner"

    graph.set_conditional_entry_point(
        pick_entry,
        {"signal_scanner": "signal_scanner", "converse": "converse"},
    )

    # Scanner → position monitor → router; converse → router
    graph.add_edge("signal_scanner", "position_monitor")
    graph.add_edge("position_monitor", "router")
    graph.add_edge("converse", "router")

    # Router conditional edges
    graph.add_conditional_edges(
        "router",
        route_from_router,
        {
            "risk_check": "risk_check",
            "strategy_update": "strategy_update",
            "backtest_run": "backtest_run",
            "notify": "notify",
            "end": END,
        },
    )

    # Branch terminations. Entry signals pause at HITL; protective exit signals
    # continue directly to execution once risk_check passes.
    graph.add_conditional_edges(
        "risk_check",
        route_after_risk,
        {
            "execute": "execute",
            "hitl_interrupt": "hitl_interrupt",
            "notify": "notify",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "hitl_interrupt",
        nodes.route_after_hitl,
        {"execute": "execute", "notify": "notify"},
    )
    graph.add_edge("execute", END)
    graph.add_edge("strategy_update", "notify")
    graph.add_edge("backtest_run", "notify")
    graph.add_edge("notify", END)

    if checkpointer is not None:
        return graph.compile(
            checkpointer=checkpointer,
            interrupt_after=["hitl_interrupt"],
        )
    return graph.compile()
