"""Tests for the HITL mode toggle (hitl_mode + edge routing + API)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from talim.app import hitl_mode
from talim.app.edges import route_after_risk
from talim.models.signal import Signal


def _entry_signal():
    return Signal(
        instrument="ES",
        strategy="momentum-US500",
        side="long",
        entry_price=5400.0,
        stop=5380.0,
        target=5440.0,
        rationale="test",
        regime_context="momentum",
    )


def _exit_signal():
    return Signal(
        instrument="ES",
        strategy="momentum-US500",
        side="long",
        entry_price=5380.0,
        stop=0.0,
        target=0.0,
        rationale="stop hit",
        regime_context="",
        action="exit",
    )


@pytest.fixture(autouse=True)
def _hitl_tmp_path(tmp_path, monkeypatch):
    """Point HITL persistence at a temp dir so tests don't touch real state."""
    monkeypatch.setattr(hitl_mode, "_DEFAULT_PATH", tmp_path / "hitl_mode.json")


class TestHitlModeModule:
    def test_default_is_enabled(self):
        assert hitl_mode.is_hitl_enabled() is True

    def test_disable(self):
        result = hitl_mode.set_hitl_enabled(False, actor="test")
        assert result["enabled"] is False
        assert result["changed_by"] == "test"
        assert result["changed_at"] is not None
        assert hitl_mode.is_hitl_enabled() is False

    def test_re_enable(self):
        hitl_mode.set_hitl_enabled(False, actor="test")
        result = hitl_mode.set_hitl_enabled(True, actor="test")
        assert result["enabled"] is True
        assert hitl_mode.is_hitl_enabled() is True

    def test_persists_to_disk(self, tmp_path):
        path = tmp_path / "hitl_mode.json"
        hitl_mode.set_hitl_enabled(False, actor="persist-test")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["enabled"] is False
        assert data["changed_by"] == "persist-test"

    def test_loads_from_disk(self, tmp_path):
        path = tmp_path / "hitl_mode.json"
        path.write_text(json.dumps({"enabled": False, "changed_by": "disk"}))
        hitl_mode._loaded = False
        hitl_mode._state["enabled"] = True
        hitl_mode._load(path)
        assert hitl_mode.is_hitl_enabled() is False

    def test_corrupt_file_defaults_to_enabled(self, tmp_path):
        path = tmp_path / "hitl_mode.json"
        path.write_text("not json {{{")
        hitl_mode._loaded = False
        hitl_mode._load(path)
        assert hitl_mode.is_hitl_enabled() is True

    def test_missing_file_defaults_to_enabled(self, tmp_path):
        hitl_mode._loaded = False
        hitl_mode._load(tmp_path / "nonexistent.json")
        assert hitl_mode.is_hitl_enabled() is True


class TestRouteAfterRiskWithHitlToggle:
    def test_entry_routes_to_hitl_when_enabled(self):
        state = {"pending_signal": _entry_signal()}
        assert route_after_risk(state) == "hitl_interrupt"

    def test_entry_routes_to_execute_when_disabled(self):
        hitl_mode.set_hitl_enabled(False)
        state = {"pending_signal": _entry_signal()}
        assert route_after_risk(state) == "execute"

    def test_exit_always_routes_to_execute(self):
        hitl_mode.set_hitl_enabled(True)
        state = {"pending_signal": _exit_signal()}
        assert route_after_risk(state) == "execute"

    def test_exit_routes_to_execute_even_when_disabled(self):
        hitl_mode.set_hitl_enabled(False)
        state = {"pending_signal": _exit_signal()}
        assert route_after_risk(state) == "execute"

    def test_no_signal_routes_to_end(self):
        hitl_mode.set_hitl_enabled(False)
        assert route_after_risk({}) == "end"


class TestHitlApiEndpoints:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setenv("TALIM_BRIDGE_SECRET", "test-secret")
        from talim.api.bridge import create_app
        app = create_app(
            bridge_message_fn=lambda **kw: {},
            resume_fn=lambda **kw: {},
            cron_trigger_fn=lambda **kw: {},
        )
        return TestClient(app)

    def test_get_hitl_default(self, client):
        resp = client.get(
            "/talim/operator/hitl",
            headers={"X-Talim-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_patch_hitl_disable(self, client):
        resp = client.patch(
            "/talim/operator/hitl",
            json={"enabled": False},
            headers={"X-Talim-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["changed_by"] == "operator"

    def test_patch_hitl_re_enable(self, client):
        client.patch(
            "/talim/operator/hitl",
            json={"enabled": False},
            headers={"X-Talim-Secret": "test-secret"},
        )
        resp = client.patch(
            "/talim/operator/hitl",
            json={"enabled": True},
            headers={"X-Talim-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_hitl_requires_auth(self, client):
        resp = client.get("/talim/operator/hitl")
        assert resp.status_code in (401, 403)

    def test_patch_hitl_requires_auth(self, client):
        resp = client.patch("/talim/operator/hitl", json={"enabled": False})
        assert resp.status_code in (401, 403)
