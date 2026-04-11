"""Tests for the real execute node (WP-23)."""

from __future__ import annotations

import pytest

from talim.app.execute_context import configure_execute, _context
from talim.app.nodes import execute
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.memory.episodic import EpisodicMemory
from talim.models.signal import Signal


def _signal(action: str = "enter", side: str = "long") -> Signal:
    return Signal(
        instrument="ES",
        strategy="momentum-ES",
        side=side,
        entry_price=5400.0,
        stop=5390.0,
        target=5420.0,
        rationale="test",
        regime_context="momentum",
        action=action,
    )


@pytest.fixture(autouse=True)
def _reset():
    yield
    _context.reset()


def test_execute_no_signal_passthrough():
    update = execute({})
    assert update == {"pending_signal": None}


def test_execute_no_exchange_logs_only():
    update = execute({"pending_signal": _signal()})
    assert update["pending_signal"] is None
    assert "would-execute" in update["last_action"]


def test_execute_places_order_and_records_decision(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem, default_qty=1.0)

    update = execute({"pending_signal": _signal(), "atr_ratio": 1.3})
    assert update["pending_signal"] is None
    assert "executed" in update["last_action"]

    positions = exchange.get_positions()
    assert any(p.instrument == "ES" for p in positions)

    rows = mem.query_decisions(instrument="ES")
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "enter"
    assert rows[0]["action"] == "approve"
    assert rows[0]["atr_ratio"] == 1.3
    mem.close()


def test_execute_exit_signal_records_signal_type_exit(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    execute({"pending_signal": _signal(action="exit", side="short")})
    row = mem.query_decisions(instrument="ES")[0]
    assert row["signal_type"] == "exit"
    mem.close()
