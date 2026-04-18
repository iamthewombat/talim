"""Tests for the order reconciliation node (WP-35)."""

from __future__ import annotations

import pytest

from talim.app.nodes.reconcile import reconcile, reconcile_positions, RepairEvent
from talim.app.execute_context import configure_execute, get_execute_context
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.memory.episodic import EpisodicMemory
from talim.models.position import Position


@pytest.fixture()
def exchange():
    return MockExchange(starting_balance=100_000.0)


@pytest.fixture()
def episodic(tmp_path):
    return EpisodicMemory(str(tmp_path / "test.db"))


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    get_execute_context().reset()


def _record_pending(episodic, instrument="ES", side="long", entry=5000.0):
    episodic.record_decision(
        timestamp="2025-06-15T10:00:00",
        instrument=instrument,
        strategy="momentum-ES",
        side=side,
        entry_price=entry,
        stop=4980.0,
        target=5030.0,
        outcome="pending",
    )


# --- reconcile_positions unit tests ---


class TestReconcilePositions:
    def test_no_divergence(self, exchange, episodic):
        """Exchange and memory agree — no repairs."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        _record_pending(episodic, "ES", "long")

        repairs = reconcile_positions(exchange, episodic)
        assert repairs == []

    def test_missing_in_memory(self, exchange, episodic):
        """Exchange has a position but memory has no pending record."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")

        repairs = reconcile_positions(exchange, episodic)
        assert len(repairs) == 1
        assert repairs[0].kind == "missing_in_memory"
        assert repairs[0].instrument == "ES"

    def test_missing_on_exchange(self, exchange, episodic):
        """Memory has a pending decision but exchange has no position."""
        _record_pending(episodic, "ES", "long")

        repairs = reconcile_positions(exchange, episodic)
        assert len(repairs) == 1
        assert repairs[0].kind == "missing_on_exchange"
        assert repairs[0].instrument == "ES"

    def test_side_mismatch(self, exchange, episodic):
        """Exchange is long but memory says short."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        _record_pending(episodic, "ES", "short")

        repairs = reconcile_positions(exchange, episodic)
        kinds = {r.kind for r in repairs}
        assert "side_mismatch" in kinds

    def test_qty_mismatch_via_state(self, exchange, episodic):
        """Exchange qty differs from state qty."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 2.0, strategy="momentum-ES")
        _record_pending(episodic, "ES", "long")

        state_pos = Position(
            instrument="ES", side="long", qty=1.0, entry_price=5000.0,
            stop=4980.0, target=5030.0, strategy="momentum-ES",
        )
        repairs = reconcile_positions(exchange, episodic, state_positions=[state_pos])
        kinds = {r.kind for r in repairs}
        assert "qty_mismatch" in kinds

    def test_multiple_instruments(self, exchange, episodic):
        """Divergences across different instruments are all reported."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        # NQ: memory says pending but exchange has nothing
        _record_pending(episodic, "NQ", "short", 15000.0)

        repairs = reconcile_positions(exchange, episodic)
        instruments = {r.instrument for r in repairs}
        assert "ES" in instruments  # missing_in_memory
        assert "NQ" in instruments  # missing_on_exchange

    def test_matching_state_no_qty_repair(self, exchange, episodic):
        """When state qty matches exchange qty, no qty_mismatch repair."""
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        _record_pending(episodic, "ES", "long")

        state_pos = Position(
            instrument="ES", side="long", qty=1.0, entry_price=5000.0,
            stop=4980.0, target=5030.0, strategy="momentum-ES",
        )
        repairs = reconcile_positions(exchange, episodic, state_positions=[state_pos])
        assert repairs == []

    def test_duplicate_cfd_state_positions_are_netted_before_comparison(self, exchange, episodic):
        exchange.set_fill_price("AU200.cash", 9000.0)
        exchange.place_order("AU200.cash", "buy", 1.0, strategy="momentum-AU200")
        _record_pending(episodic, "AU200.cash", "long", 9000.0)

        repairs = reconcile_positions(
            exchange,
            episodic,
            state_positions=[
                Position(
                    instrument="AU200.cash",
                    side="long",
                    qty=0.6,
                    entry_price=9000.0,
                    stop=8950.0,
                    target=9075.0,
                    strategy="momentum-AU200",
                ),
                Position(
                    instrument="AU200.cash",
                    side="long",
                    qty=0.4,
                    entry_price=9001.0,
                    stop=8951.0,
                    target=9076.0,
                    strategy="momentum-AU200",
                ),
            ],
        )
        assert repairs == []


# --- reconcile node tests ---


class TestReconcileNode:
    def test_no_context_skips(self):
        """Without exchange/episodic configured, node is a no-op."""
        result = reconcile({})
        assert result == {}

    def test_no_divergence_no_notification(self, exchange, episodic):
        configure_execute(exchange, episodic)
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        _record_pending(episodic, "ES", "long")

        result = reconcile({"active_positions": []})
        assert "pending_notification" not in result

    def test_divergence_surfaces_notification(self, exchange, episodic):
        configure_execute(exchange, episodic)
        exchange.set_fill_price("ES", 5000.0)
        exchange.place_order("ES", "buy", 1.0, strategy="momentum-ES")
        # No matching memory record → missing_in_memory

        result = reconcile({"active_positions": []})
        assert "pending_notification" in result
        assert "missing_in_memory" in result["pending_notification"]
        assert "ES" in result["pending_notification"]

    def test_repair_event_to_dict(self):
        r = RepairEvent(
            kind="missing_in_memory",
            instrument="ES",
            detail="test detail",
            timestamp="2025-06-15T10:00:00",
        )
        d = r.to_dict()
        assert d["kind"] == "missing_in_memory"
        assert d["instrument"] == "ES"
