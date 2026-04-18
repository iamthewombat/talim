"""Tests for the Talim bridge API."""

import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app
SECRET = "test-secret-shhh"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)


@pytest.fixture
def fake_bridge_calls():
    return []


@pytest.fixture
def fake_resume_calls():
    return []


@pytest.fixture
def fake_trigger_calls():
    return []


@pytest.fixture
def app(fake_bridge_calls, fake_resume_calls, fake_trigger_calls):
    def fake_bridge(message, thread_id):
        fake_bridge_calls.append((message, thread_id))
        return {
            "response_message": f"echo:{message}",
            "thread_id": thread_id,
        }

    def fake_resume(thread_id, approved):
        fake_resume_calls.append((thread_id, approved))
        return {
            "thread_id": thread_id,
            "signal_approved": approved,
            "pending_signal": None,
        }

    def fake_cron(thread_id="cron-main", **kwargs):
        fake_trigger_calls.append(thread_id)
        return {"last_scan_time": "2025-06-15T10:00:00", "thread_id": thread_id}

    return create_app(
        bridge_message_fn=fake_bridge,
        resume_fn=fake_resume,
        cron_trigger_fn=fake_cron,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# /talim/health (no auth)
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health(self, client):
        r = client.get("/talim/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /talim/converse
# ---------------------------------------------------------------------------

class TestConverseEndpoint:
    def test_requires_secret(self, client):
        r = client.post("/talim/converse", json={"message": "hi"})
        assert r.status_code == 401

    def test_rejects_wrong_secret(self, client):
        r = client.post(
            "/talim/converse",
            json={"message": "hi"},
            headers={"X-Talim-Secret": "wrong"},
        )
        assert r.status_code == 401

    def test_invokes_bridge(self, client, fake_bridge_calls):
        r = client.post(
            "/talim/converse",
            json={"message": "what's my P&L?", "thread_id": "t-1"},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["thread_id"] == "t-1"
        assert body["response_message"] == "echo:what's my P&L?"
        assert "response_message" in body["state_keys"]
        assert fake_bridge_calls == [("what's my P&L?", "t-1")]

    def test_validation_rejects_empty(self, client):
        r = client.post(
            "/talim/converse",
            json={"message": ""},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# /talim/resume
# ---------------------------------------------------------------------------

class TestResumeEndpoint:
    def test_requires_secret(self, client):
        r = client.post("/talim/resume", json={"thread_id": "x", "approved": True})
        assert r.status_code == 401

    def test_approve(self, client, fake_resume_calls):
        r = client.post(
            "/talim/resume",
            json={"thread_id": "t-1", "approved": True},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "thread_id": "t-1",
            "approved": True,
            "pending_signal_cleared": True,
        }
        assert fake_resume_calls == [("t-1", True)]

    def test_reject(self, client, fake_resume_calls):
        r = client.post(
            "/talim/resume",
            json={"thread_id": "t-2", "approved": False},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        assert fake_resume_calls == [("t-2", False)]


# ---------------------------------------------------------------------------
# /talim/trigger
# ---------------------------------------------------------------------------

class TestTriggerEndpoint:
    def test_requires_secret(self, client):
        r = client.post("/talim/trigger")
        assert r.status_code == 401

    def test_trigger_default_thread(self, client, fake_trigger_calls):
        r = client.post(
            "/talim/trigger",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["triggered"] is True
        assert body["thread_id"] == "cron-main"
        assert "last_scan_time" in body["state_keys"]
        assert fake_trigger_calls == ["cron-main"]

    def test_trigger_custom_thread(self, client, fake_trigger_calls):
        r = client.post(
            "/talim/trigger?thread_id=scan-42",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        assert r.json()["thread_id"] == "scan-42"
        assert fake_trigger_calls == ["scan-42"]


# ---------------------------------------------------------------------------
# End-to-end with real bridge_message (no LLM client)
# ---------------------------------------------------------------------------

class TestRealRoundTrip:
    def test_real_bridge_message(self, monkeypatch):
        monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
        app = create_app()  # use the real entry points
        client = TestClient(app)
        r = client.post(
            "/talim/converse",
            json={"message": "what's my P&L?", "thread_id": "real-1"},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        # Real notify with no LLM client falls back to "ack".
        assert body["response_message"] == "ack"
