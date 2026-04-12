"""Tests for risk config validation and kill switch (WP-39)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app, set_halted
from talim.app.nodes.risk_check import risk_check
from talim.models.signal import Signal
from talim.risk.config import (
    RiskConfigError,
    load_validated_config,
    validate_config,
)


# --- Config validation ---


class TestValidateConfig:
    def test_valid_config(self):
        data = {
            "max_position_qty": 5.0,
            "max_total_exposure": 100_000.0,
            "max_daily_drawdown": -2000.0,
            "max_correlated_positions": 1,
        }
        assert validate_config(data) == []

    def test_missing_required_fields(self):
        errors = validate_config({})
        assert len(errors) == 1
        assert "missing required fields" in errors[0]

    def test_negative_qty_rejected(self):
        data = {
            "max_position_qty": -1,
            "max_total_exposure": 100_000.0,
            "max_daily_drawdown": -2000.0,
            "max_correlated_positions": 1,
        }
        errors = validate_config(data)
        assert any("max_position_qty" in e for e in errors)

    def test_positive_drawdown_rejected(self):
        data = {
            "max_position_qty": 5.0,
            "max_total_exposure": 100_000.0,
            "max_daily_drawdown": 500.0,
            "max_correlated_positions": 1,
        }
        errors = validate_config(data)
        assert any("max_daily_drawdown" in e for e in errors)

    def test_negative_correlated_rejected(self):
        data = {
            "max_position_qty": 5.0,
            "max_total_exposure": 100_000.0,
            "max_daily_drawdown": -2000.0,
            "max_correlated_positions": -1,
        }
        errors = validate_config(data)
        assert any("max_correlated_positions" in e for e in errors)

    def test_bad_correlation_groups(self):
        data = {
            "max_position_qty": 5.0,
            "max_total_exposure": 100_000.0,
            "max_daily_drawdown": -2000.0,
            "max_correlated_positions": 1,
            "correlation_groups": "not-a-list",
        }
        errors = validate_config(data)
        assert any("correlation_groups" in e for e in errors)


class TestLoadValidatedConfig:
    def test_loads_valid_file(self, tmp_path):
        cfg = tmp_path / "risk.json"
        cfg.write_text(json.dumps({
            "max_position_qty": 3.0,
            "max_total_exposure": 50_000.0,
            "max_daily_drawdown": -1000.0,
            "max_correlated_positions": 2,
        }))
        rules = load_validated_config(cfg)
        assert rules.max_position_qty == 3.0
        assert rules.max_total_exposure == 50_000.0

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RiskConfigError, match="not found"):
            load_validated_config(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("{invalid")
        with pytest.raises(RiskConfigError, match="invalid JSON"):
            load_validated_config(cfg)

    def test_validation_failure_raises(self, tmp_path):
        cfg = tmp_path / "risk.json"
        cfg.write_text(json.dumps({"max_position_qty": -5}))
        with pytest.raises(RiskConfigError, match="validation failed"):
            load_validated_config(cfg)


# --- Kill switch (risk_check halted) ---


def _signal() -> Signal:
    return Signal(
        instrument="ES", strategy="momentum-ES", side="long",
        entry_price=5000.0, stop=4980.0, target=5030.0,
        rationale="test", regime_context="momentum",
    )


class TestHaltedRiskCheck:
    def test_halted_blocks_signal(self):
        state = {"pending_signal": _signal(), "halted": True}
        result = risk_check(state)
        assert result["pending_signal"] is None
        assert result["signal_approved"] is False
        assert "HALTED" in result["pending_notification"]

    def test_not_halted_passes_through(self):
        state = {"pending_signal": _signal(), "halted": False}
        result = risk_check(state)
        # No blocking — risk_check returns {} on pass-through
        assert result == {}


# --- Kill switch endpoints ---


SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
    set_halted(False)


@pytest.fixture
def client():
    def noop_bridge(message, thread_id):
        return {"response_message": "ok"}

    def noop_resume(thread_id, approved):
        return {"pending_signal": None}

    def noop_cron(thread_id="cron-main", initial_state=None, **kwargs):
        return {"halted": (initial_state or {}).get("halted", False)}

    app = create_app(
        bridge_message_fn=noop_bridge,
        resume_fn=noop_resume,
        cron_trigger_fn=noop_cron,
    )
    return TestClient(app)


class TestHaltEndpoints:
    def test_halt_requires_secret(self, client):
        assert client.post("/talim/halt").status_code == 401

    def test_halt_activates(self, client):
        r = client.post("/talim/halt", headers={"X-Talim-Secret": SECRET})
        assert r.status_code == 200
        assert r.json()["halted"] is True

    def test_resume_trading_clears(self, client):
        client.post("/talim/halt", headers={"X-Talim-Secret": SECRET})
        r = client.post("/talim/resume-trading", headers={"X-Talim-Secret": SECRET})
        assert r.status_code == 200
        assert r.json()["halted"] is False

    def test_halt_status_no_auth(self, client):
        r = client.get("/talim/halt-status")
        assert r.status_code == 200
        assert r.json()["halted"] is False

    def test_halt_status_reflects_halt(self, client):
        client.post("/talim/halt", headers={"X-Talim-Secret": SECRET})
        r = client.get("/talim/halt-status")
        assert r.json()["halted"] is True

    def test_trigger_injects_halted(self, client):
        client.post("/talim/halt", headers={"X-Talim-Secret": SECRET})
        r = client.post("/talim/trigger", headers={"X-Talim-Secret": SECRET})
        assert r.status_code == 200
        # The fake cron echoes back the halted state it received
        assert "halted" in r.json()["state_keys"]
