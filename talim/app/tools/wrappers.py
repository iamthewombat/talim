"""Tool wrapper functions (WP-27).

Each is a thin shim around an existing Talim subsystem and returns a
JSON-serialisable dict. New tools should be added to the `TOOLS` registry at
the bottom so the MCP server can introspect the full set.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from talim.app.tools.context import ToolContext
from talim.backtest.engine import run_backtest as _run_backtest
from talim.llm import prompts
from talim.llm.client import LLMUnavailable
from talim.models.position import Position


class ToolError(RuntimeError):
    pass


def _require(ctx: ToolContext, attr: str) -> Any:
    value = getattr(ctx, attr, None)
    if value is None:
        raise ToolError(f"tool requires ctx.{attr} but it is None")
    return value


def _position_to_dict(p: Position) -> dict:
    return {
        "instrument": p.instrument,
        "side": p.side,
        "qty": p.qty,
        "entry_price": p.entry_price,
        "stop": p.stop,
        "target": p.target,
        "strategy": p.strategy,
        "open_pnl": p.open_pnl,
    }


def get_positions(ctx: ToolContext) -> dict:
    """Return current open positions on the configured exchange."""
    exchange = _require(ctx, "exchange")
    positions = exchange.get_positions()
    return {"positions": [_position_to_dict(p) for p in positions]}


def get_pnl(ctx: ToolContext) -> dict:
    """Return open and account-balance P&L numbers."""
    exchange = _require(ctx, "exchange")
    positions = exchange.get_positions()
    open_pnl = sum(float(p.open_pnl or 0.0) for p in positions)
    balance = exchange.get_account_balance()
    return {
        "open_pnl": open_pnl,
        "position_count": len(positions),
        "balance": balance,
    }


def run_backtest(
    ctx: ToolContext,
    *,
    strategy_name: str,
    param_variants: list[dict],
    df: pd.DataFrame | None = None,
) -> dict:
    """Run the on_bar backtest engine and return sorted-by-Sharpe results."""
    if df is None:
        raise ToolError("run_backtest requires a DataFrame (PoC: pass df explicitly)")
    results = _run_backtest(strategy_name, param_variants=param_variants, df=df)
    return {
        "results": [
            {
                "strategy_name": r.strategy_name,
                "net_pnl": r.net_pnl,
                "sharpe_ratio": r.sharpe_ratio,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
                "param_variant": r.param_variant,
            }
            for r in results
        ]
    }


def propose_strategy_update(
    ctx: ToolContext,
    *,
    strategy_name: str,
    current_params: dict,
    regime: str,
) -> dict:
    """Ask the LLM for a parameter proposal — same prompt the node uses."""
    llm = _require(ctx, "llm")
    prompt = prompts.strategy_reasoning_prompt(
        strategy_name=strategy_name,
        current_params=current_params,
        regime=regime,
    )
    try:
        response = llm.reason(prompt)
    except LLMUnavailable as e:
        return {"proposal": None, "error": str(e)}

    text = (response.text or "").strip()
    proposal: dict | None = None
    try:
        proposal = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                proposal = json.loads(text[s : e + 1])
            except json.JSONDecodeError:
                proposal = None
    return {"proposal": proposal, "raw": text}


def query_episodic_memory(
    ctx: ToolContext,
    *,
    instrument: str | None = None,
    strategy: str | None = None,
    limit: int = 50,
) -> dict:
    """Query the episodic decision log."""
    mem = _require(ctx, "episodic")
    rows = mem.query_decisions(instrument=instrument, strategy=strategy)
    return {"decisions": rows[:limit], "total": len(rows)}


# Registry consumed by the MCP server. Each entry: (name, callable, description).
TOOLS = [
    ("get_positions", get_positions, "List current open positions."),
    ("get_pnl", get_pnl, "Get open P&L and account balance."),
    ("run_backtest", run_backtest, "Run a multi-variant on_bar backtest."),
    (
        "propose_strategy_update",
        propose_strategy_update,
        "LLM-driven proposal for strategy parameter changes.",
    ),
    (
        "query_episodic_memory",
        query_episodic_memory,
        "Query the episodic decision log.",
    ),
]
