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
        strategy="momentum-US500",
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
    assert positions[0].stop == 5390.0
    assert positions[0].target == 5420.0
    assert len(update["active_positions"]) == 1

    order = exchange.get_order(positions[0].position_id)
    assert order is not None
    assert order.stop_price == 5390.0
    assert order.target_price == 5420.0

    rows = mem.query_decisions(instrument="ES")
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "enter"
    assert rows[0]["action"] == "approve"
    assert rows[0]["atr_ratio"] == 1.3
    mem.close()


def test_execute_exit_signal_records_signal_type_exit(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    exchange.place_order("ES", "sell", 1.0, strategy="momentum-US500")
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    execute({
        "pending_signal": _signal(action="exit", side="short"),
        "active_positions": exchange.get_positions(),
    })
    row = mem.query_decisions(instrument="ES")[0]
    assert row["signal_type"] == "exit"
    mem.close()


def test_execute_exit_signal_closes_long_with_sell(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    exchange.place_order("ES", "buy", 2.0, strategy="momentum-US500")
    exchange.set_fill_price("ES", 5410.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    update = execute({
        "pending_signal": _signal(action="exit", side="long"),
        "active_positions": exchange.get_positions(),
    })

    assert update["pending_signal"] is None
    assert update["active_positions"] == []
    assert exchange.get_positions() == []
    row = mem.query_decisions(instrument="ES")[0]
    assert row["signal_type"] == "exit"
    assert row["outcome"] == "closed"
    assert "order_side=sell" in row["notes"]
    mem.close()


def test_execute_exit_signal_closes_short_with_buy(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    exchange.place_order("ES", "sell", 1.0, strategy="momentum-US500")
    exchange.set_fill_price("ES", 5390.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    update = execute({
        "pending_signal": _signal(action="exit", side="short"),
        "active_positions": exchange.get_positions(),
    })

    assert update["active_positions"] == []
    assert exchange.get_positions() == []
    row = mem.query_decisions(instrument="ES")[0]
    assert "order_side=buy" in row["notes"]
    mem.close()


def test_execute_exit_skips_when_no_matching_position():
    exchange = MockExchange(starting_balance=100_000.0)
    configure_execute(exchange)

    update = execute({"pending_signal": _signal(action="exit", side="long")})

    assert update["pending_signal"] is None
    assert "execute-skipped exit long ES" in update["last_action"]
    assert exchange.get_positions() == []


def test_execute_exit_fires_closeout_push(tmp_path, monkeypatch):
    captured: list = []

    def _capture(event, **_kwargs):
        captured.append(event)
        return True

    monkeypatch.setattr(
        "talim.connectors.discord.closeout.post_closeout", _capture
    )

    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    exchange.place_order("ES", "buy", 2.0, strategy="momentum-US500")
    exchange.set_fill_price("ES", 5420.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    execute({
        "pending_signal": _signal(action="exit", side="long"),
        "active_positions": exchange.get_positions(),
    })

    assert len(captured) == 1
    event = captured[0]
    assert event.instrument == "ES"
    assert event.side == "long"
    assert event.qty == 2.0
    assert event.entry_price == 5400.0
    assert event.exit_price == 5420.0
    assert event.pnl == pytest.approx(40.0)
    mem.close()


def test_execute_exit_flips_matching_pending_entry_to_closed(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    # Approve an entry — leaves a pending row in episodic.
    execute({"pending_signal": _signal(action="enter", side="long")})
    rows = mem.query_decisions(instrument="ES")
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "enter"
    assert rows[0]["outcome"] == "pending"

    # Approve the matching exit — should flip the entry to closed.
    exchange.set_fill_price("ES", 5410.0)
    execute({
        "pending_signal": _signal(action="exit", side="long"),
        "active_positions": exchange.get_positions(),
    })

    rows = mem.query_decisions(instrument="ES")
    by_type = {r["signal_type"]: r for r in rows}
    assert by_type["enter"]["outcome"] == "closed"
    assert by_type["exit"]["outcome"] == "closed"
    mem.close()


def test_execute_exit_only_flips_matching_instrument_and_side(tmp_path):
    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    execute({"pending_signal": _signal(action="enter", side="long")})
    # Sibling pending entries that must NOT be touched.
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc).isoformat()
    mem.record_decision(
        timestamp=now, instrument="NQ", strategy="momentum-US500", side="long",
        entry_price=20_000.0, stop=19_900.0, target=20_200.0,
        signal_type="enter", outcome="pending",
    )
    mem.record_decision(
        timestamp=now, instrument="ES", strategy="momentum-US500", side="short",
        entry_price=5400.0, stop=5420.0, target=5360.0,
        signal_type="enter", outcome="pending",
    )

    exchange.set_fill_price("ES", 5410.0)
    execute({
        "pending_signal": _signal(action="exit", side="long"),
        "active_positions": exchange.get_positions(),
    })

    rows = mem.query_decisions()
    by_key = {(r["instrument"], r["side"], r["signal_type"]): r for r in rows}
    assert by_key[("ES", "long", "enter")]["outcome"] == "closed"
    assert by_key[("NQ", "long", "enter")]["outcome"] == "pending"
    assert by_key[("ES", "short", "enter")]["outcome"] == "pending"
    mem.close()


def test_execute_enter_does_not_fire_closeout(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(
        "talim.connectors.discord.closeout.post_closeout",
        lambda event, **_: captured.append(event) or True,
    )

    exchange = MockExchange(starting_balance=100_000.0)
    exchange.set_fill_price("ES", 5400.0)
    mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
    configure_execute(exchange, episodic=mem)

    execute({"pending_signal": _signal()})

    assert captured == []
    mem.close()
