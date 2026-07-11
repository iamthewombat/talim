"""Tests for the operator/OpenClaw HITL and sync APIs (WP-64/WP-65)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app
from talim.app.demo_harness import build_mock_execution_data
from talim.app.execute_context import get_execute_context
from talim.app.nodes.risk_check import configure_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.connectors.exchange.mock_exchange import MockExchange
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.risk.rules import RiskRules

SECRET = "operator-secret"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
    yield
    scanner_context.reset()
    get_execute_context().reset()
    configure_risk_rules(RiskRules())


@pytest.fixture
def operator_client(monkeypatch, tmp_path):
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
    monkeypatch.setenv("TALIM_PRICEFEED", "mock")
    monkeypatch.setenv("TALIM_INSTRUMENTS", "ES")
    monkeypatch.setenv("TALIM_STRATEGIES", "momentum-US500")
    monkeypatch.setenv("TALIM_CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("TALIM_EPISODIC_DB", str(tmp_path / "episodic.db"))
    monkeypatch.setenv("TALIM_RISK_CONFIG", "")

    app = create_app()
    runtime = app.state.talim_runtime
    assert isinstance(runtime.price_feed, MockPriceFeed)
    assert isinstance(runtime.exchange, MockExchange)

    runtime.price_feed.load(build_mock_execution_data())
    runtime.price_feed.connect()
    runtime.price_feed.replay()
    runtime.exchange.set_fill_price("ES", 5000)
    configure_risk_rules(RiskRules(
        max_total_exposure=10_000_000.0,
        block_on_existing_same_instrument=False,
        max_correlated_positions=5,
    ))
    return TestClient(app), runtime


def _auth() -> dict[str, str]:
    return {"X-Talim-Secret": SECRET}


def test_operator_endpoints_require_runtime_when_app_is_injected():
    app = create_app(
        bridge_message_fn=lambda **_: {},
        resume_fn=lambda **_: {},
        cron_trigger_fn=lambda **_: {},
    )
    client = TestClient(app)

    response = client.get("/talim/operator/status", headers=_auth())

    assert response.status_code == 503
    assert client.post("/talim/sync", headers=_auth()).status_code == 503


def test_operator_status_returns_runtime_shape(operator_client):
    client, _runtime = operator_client

    response = client.get("/talim/operator/status", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["halted"] is False
    assert body["runtime"]["exchange_mode"] == "mock"
    assert body["runtime"]["instruments"] == ["ES"]
    assert body["runtime"]["strategies"] == ["momentum-US500"]
    assert body["runtime"]["subscriptions"] == ["ES"]


def test_operator_pending_and_decision_approve_full_path(operator_client):
    client, runtime = operator_client

    trigger = client.post("/talim/trigger?thread_id=op-1", headers=_auth())
    assert trigger.status_code == 200

    pending = client.get("/talim/operator/pending?thread_id=op-1", headers=_auth())
    assert pending.status_code == 200
    pending_body = pending.json()
    assert pending_body["paused"] is True
    assert pending_body["pending_signal"]["strategy"] == "momentum-US500"

    runtime.exchange.set_fill_price("ES", pending_body["pending_signal"]["entry_price"])
    decision = client.post(
        "/talim/operator/decision",
        json={"thread_id": "op-1", "approved": True},
        headers=_auth(),
    )

    assert decision.status_code == 200
    decision_body = decision.json()
    assert decision_body["pending_signal_cleared"] is True
    assert "executed enter" in decision_body["last_action"]

    positions = client.get("/talim/operator/positions", headers=_auth())
    assert positions.status_code == 200
    assert positions.json()["positions"][0]["instrument"] == "ES"

    decisions = client.get("/talim/operator/decisions?instrument=ES", headers=_auth())
    assert decisions.status_code == 200
    decision_rows = decisions.json()["decisions"]
    assert len(decision_rows) == 1
    assert decision_rows[0]["strategy"] == "momentum-US500"
    # WP-85 trade-pairing columns flow through to the operator API.
    assert decision_rows[0]["qty"] is not None
    assert decision_rows[0]["entry_decision_id"] is None


def test_operator_decision_reject_clears_pending_without_order(operator_client):
    client, runtime = operator_client

    client.post("/talim/trigger?thread_id=op-reject", headers=_auth())
    decision = client.post(
        "/talim/operator/decision",
        json={"thread_id": "op-reject", "approved": False},
        headers=_auth(),
    )

    assert decision.status_code == 200
    assert decision.json()["pending_signal_cleared"] is True
    assert runtime.exchange.get_positions() == []
    assert runtime.episodic.query_decisions() == []


def test_sync_skips_checkpoint_update_while_hitl_thread_is_paused(operator_client):
    client, _runtime = operator_client

    client.post("/talim/trigger?thread_id=op-paused", headers=_auth())

    response = client.post("/talim/sync?thread_id=op-paused", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["paused"] is True
    assert body["state_updated"] is False
    assert body["repair_count"] == 0

    pending = client.get("/talim/operator/pending?thread_id=op-paused", headers=_auth())
    assert pending.json()["paused"] is True
    assert pending.json()["pending_signal"]["strategy"] == "momentum-US500"


def test_sync_after_approval_persists_positions_and_pnl(operator_client):
    client, runtime = operator_client

    client.post("/talim/trigger?thread_id=op-sync", headers=_auth())
    pending = client.get("/talim/operator/pending?thread_id=op-sync", headers=_auth())
    runtime.exchange.set_fill_price("ES", pending.json()["pending_signal"]["entry_price"])
    client.post(
        "/talim/operator/decision",
        json={"thread_id": "op-sync", "approved": True},
        headers=_auth(),
    )

    response = client.post("/talim/sync?thread_id=op-sync", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["paused"] is False
    assert body["state_updated"] is True
    assert body["position_count"] == 1
    assert body["pnl"]["position_count"] == 1
    assert body["repair_count"] == 0

    snapshot = runtime.snapshot(thread_id="op-sync")
    assert len(snapshot.values["active_positions"]) == 1
    assert snapshot.values["account_balance"] == body["pnl"]["account_balance"]
    assert snapshot.values["last_action"] == "synced broker state"


def test_sync_reports_reconciliation_repairs(operator_client):
    client, runtime = operator_client
    runtime.exchange.set_fill_price("ES", 5000)
    runtime.exchange.place_order("ES", "buy", 1, strategy="manual")

    response = client.post("/talim/sync?thread_id=op-repair", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["state_updated"] is True
    assert body["repair_count"] == 1
    assert body["repairs"][0]["kind"] == "missing_in_memory"
    assert "missing_in_memory" in body["pending_notification"]

    snapshot = runtime.snapshot(thread_id="op-repair")
    assert "missing_in_memory" in snapshot.values["pending_notification"]


def test_sync_clears_stale_reconciliation_notification(operator_client):
    client, runtime = operator_client
    runtime.exchange.set_fill_price("ES", 5000)
    runtime.exchange.place_order("ES", "buy", 1, strategy="manual")
    client.post("/talim/sync?thread_id=op-clear-repair", headers=_auth())
    runtime.exchange.place_order("ES", "sell", 1, strategy="manual")

    response = client.post("/talim/sync?thread_id=op-clear-repair", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["repair_count"] == 0
    assert body["pending_notification"] is None
    snapshot = runtime.snapshot(thread_id="op-clear-repair")
    assert snapshot.values["pending_notification"] is None
