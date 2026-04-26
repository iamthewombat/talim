"""Deterministic demo execution harness for the live runtime path.

The harness proves the same runtime components used by FastAPI can complete a
paper execution loop before real broker demo credentials are used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from talim.app.graph import build_graph
from talim.app.execute_context import get_execute_context
from talim.app.nodes.reconcile import reconcile_positions
from talim.app.nodes.risk_check import configure_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.app.runtime import RuntimeConfig, bootstrap_runtime
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.models.signal import Signal
from talim.risk.rules import RiskRules


class DemoHarnessError(RuntimeError):
    """Raised when the demo execution path does not reach the expected state."""


@dataclass(frozen=True, slots=True)
class DemoExecutionResult:
    """Summary of one completed demo execution."""

    thread_id: str
    instrument: str
    strategy: str
    side: str
    entry_price: float
    order_count: int
    position_count: int
    decision_count: int
    account_balance: float
    last_action: str
    reconcile_divergences: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_mock_execution_data(n: int = 180, freq: str = "5min") -> pd.DataFrame:
    """Create deterministic bars that make the baseline momentum strategy fire."""
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.15)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-06-15 09:30", periods=n, freq=freq),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10_000.0),
    })


def run_mock_demo_execution(
    *,
    state_dir: str | Path,
    thread_id: str = "demo-exec-1",
    instrument: str = "ES",
    strategy: str = "momentum-US500",
    qty: float = 1.0,
    bar_window: int = 80,
    data: pd.DataFrame | None = None,
) -> DemoExecutionResult:
    """Run scan -> HITL -> approve -> execute -> reconcile using MockExchange."""
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)

    config = RuntimeConfig(
        exchange_mode="mock",
        exchange_name=None,
        pricefeed_name="mock",
        pricefeed_timeframe="5m",
        instruments=(instrument,),
        strategies=(strategy,),
        default_qty=qty,
        bar_window=bar_window,
        checkpoint_db=state_path / "talim_checkpoints.db",
        episodic_db=state_path / "episodic.db",
        risk_config_path=None,
    )
    runtime = bootstrap_runtime(config)
    try:
        if not isinstance(runtime.price_feed, MockPriceFeed):
            raise DemoHarnessError("mock demo requires MockPriceFeed")
        if not isinstance(runtime.exchange, MockExchange):
            raise DemoHarnessError("mock demo requires MockExchange")

        runtime.price_feed.load(data if data is not None else build_mock_execution_data())
        runtime.price_feed.connect()
        runtime.price_feed.replay()
        runtime.exchange.set_fill_price(instrument, 5000.0)

        # Keep paper risk permissive enough that the harness validates execution,
        # not unrelated position-size defaults.
        configure_risk_rules(RiskRules(
            max_total_exposure=10_000_000.0,
            block_on_existing_same_instrument=False,
            max_correlated_positions=5,
        ))

        runtime.cron_trigger(thread_id=thread_id)
        graph = build_graph(checkpointer=runtime.checkpointer)
        graph_config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(graph_config)
        if snapshot is None or not snapshot.next:
            raise DemoHarnessError("graph did not pause for HITL approval")

        pending = snapshot.values.get("pending_signal")
        if not isinstance(pending, Signal):
            raise DemoHarnessError("scanner did not produce a pending signal")

        # Fill at the strategy's entry for deterministic paper balances.
        runtime.exchange.set_fill_price(instrument, pending.entry_price)
        final = runtime.resume(thread_id=thread_id, approved=True)
        if final.get("pending_signal") is not None:
            raise DemoHarnessError("pending signal was not cleared after approval")
        if "executed" not in str(final.get("last_action", "")):
            raise DemoHarnessError(
                f"execute did not report success: {final.get('last_action')}"
            )

        positions = runtime.exchange.get_positions()
        decisions = runtime.episodic.query_decisions(instrument=instrument)
        repairs = reconcile_positions(runtime.exchange, runtime.episodic, positions)
        balance = runtime._safe_account_balance(positions) or 0.0

        return DemoExecutionResult(
            thread_id=thread_id,
            instrument=instrument,
            strategy=strategy,
            side=pending.side,
            entry_price=pending.entry_price,
            order_count=len(runtime.exchange._orders),  # noqa: SLF001 - harness summary only
            position_count=len(positions),
            decision_count=len(decisions),
            account_balance=balance,
            last_action=str(final.get("last_action")),
            reconcile_divergences=len(repairs),
        )
    finally:
        runtime.episodic.close()
        scanner_context.reset()
        get_execute_context().reset()
        configure_risk_rules(RiskRules())
