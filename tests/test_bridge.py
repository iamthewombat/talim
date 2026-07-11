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

class TestOperatorDashboard:
    """Smoke test that the WP-69 static dashboard is mounted and reachable."""

    def test_index_html_loads(self, client):
        r = client.get("/talim/dashboard/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Talim Operator" in r.text

    def test_no_trailing_slash_also_loads(self, client):
        r = client.get("/talim/dashboard")
        # StaticFiles html=True redirects or serves index for the mount root.
        assert r.status_code in (200, 307)

    def test_assets_served(self, client):
        r = client.get("/talim/dashboard/app.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        assert "refreshStatus" in r.text

        r = client.get("/talim/dashboard/ui.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        assert "TalimUI" in r.text
        assert "promptSecret" in r.text

        r = client.get("/talim/dashboard/style.css")
        assert r.status_code == 200
        assert "text/css" in r.headers["content-type"]
        assert "overscroll-behavior: contain" in r.text
        assert "touch-action: none" in r.text

    def test_signal_page_assets_served(self, client):
        r = client.get("/talim/dashboard/signal.html")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Talim Signal" in r.text
        assert "signal.js" in r.text
        assert "lightweight-charts" in r.text
        assert "id=\"signal-chart\"" in r.text
        assert "id=\"decision-context-body\"" in r.text
        assert "Decision context" in r.text
        assert "viewport" in r.text

        r = client.get("/talim/dashboard/signal.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        assert "/talim/operator/signals/" in r.text
        assert "CHART_INITIAL_BEFORE = 160" in r.text
        assert "CHART_INITIAL_AFTER = 60" in r.text
        assert "subscribeVisibleLogicalRangeChange" in r.text
        assert "refreshLiveOnly" in r.text
        assert "setInterval(refreshLiveOnly, 15000)" in r.text
        assert "/talim/operator/decision" in r.text
        assert "createPriceLine" in r.text
        assert "setMarkers" in r.text
        assert "renderDecisionContext" in r.text
        assert "EMA(8) crossed" in r.text
        assert "Approval gate" in r.text

    def test_dashboard_is_public_html_shell(self, client):
        # The HTML shell is public so the operator can load the page before
        # pasting their secret. The JS inside makes authenticated API calls.
        r = client.get("/talim/dashboard/")
        assert r.status_code == 200
        # But the API calls the dashboard makes still require the secret.
        r = client.get("/talim/operator/status")
        assert r.status_code == 401


class TestRealRoundTrip:
    def test_real_bridge_message(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
        monkeypatch.setenv("TALIM_CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
        monkeypatch.setenv("TALIM_EPISODIC_DB", str(tmp_path / "episodic.db"))
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


class TestOperatorDecisionEndpoint:
    def test_passes_signal_id_to_runtime(self, client):
        calls = []

        class FakeRuntime:
            def resume(self, *, thread_id, approved, signal_id=None):
                calls.append((thread_id, approved, signal_id))
                return {
                    "pending_signal": None,
                    "last_action": f"handled {signal_id}",
                }

        client.app.state.talim_runtime = FakeRuntime()
        r = client.post(
            "/talim/operator/decision",
            json={"thread_id": "cron-main", "approved": False, "signal_id": "SIG-123"},
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 200
        assert r.json()["last_action"] == "handled SIG-123"
        assert calls == [("cron-main", False, "SIG-123")]


class TestOperatorSignalChartEndpoint:
    def test_requires_secret(self, client):
        r = client.get("/talim/operator/signals/SIG-123/chart")
        assert r.status_code == 401

    def test_returns_chart_from_runtime(self, client):
        calls = []

        class FakeRuntime:
            def operator_signal_chart(self, *, signal_id, before=50, after=20):
                calls.append((signal_id, before, after))
                return {
                    "signal_id": signal_id,
                    "status": "ok",
                    "source": "scanner_history",
                    "timeframe": "5m",
                    "requested": {"before": before, "after": after},
                    "signal": {"instrument": "US500.cash"},
                    "candles": [],
                    "indicators": {},
                    "levels": {},
                    "warnings": [],
                }

        client.app.state.talim_runtime = FakeRuntime()
        r = client.get(
            "/talim/operator/signals/SIG-123/chart?before=20&after=7",
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 200
        assert r.json()["requested"] == {"before": 20, "after": 7}
        assert calls == [("SIG-123", 20, 7)]

    def test_returns_404_for_unknown_signal(self, client):
        class FakeRuntime:
            def operator_signal_chart(self, *, signal_id, before=50, after=20):
                return None

        client.app.state.talim_runtime = FakeRuntime()
        r = client.get(
            "/talim/operator/signals/SIG-MISSING/chart",
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 404


class TestOperatorPositionsDashboardEndpoint:
    def test_requires_secret(self, client):
        r = client.get("/talim/operator/positions/dashboard")
        assert r.status_code == 401

    def test_returns_enriched_positions_from_runtime(self, client):
        class FakeRuntime:
            def operator_positions_dashboard(self):
                return {
                    "summary": {"position_count": 1, "mark_open_pnl": -12.5},
                    "positions": [{"position_id": "P1", "instrument": "US500.cash"}],
                }

        client.app.state.talim_runtime = FakeRuntime()
        r = client.get(
            "/talim/operator/positions/dashboard",
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 200
        assert r.json()["summary"]["mark_open_pnl"] == -12.5
        assert r.json()["positions"][0]["position_id"] == "P1"


class TestOperatorPositionChartEndpoint:
    def test_requires_secret(self, client):
        r = client.get("/talim/operator/positions/P1/chart")
        assert r.status_code == 401

    def test_returns_chart_from_runtime(self, client):
        calls = []

        class FakeRuntime:
            def operator_position_chart(self, *, position_id, bars=240):
                calls.append((position_id, bars))
                return {
                    "position_id": position_id,
                    "status": "ok",
                    "source": "broker_recent",
                    "timeframe": "5m",
                    "requested": {"bars": bars},
                    "position": {"position_id": position_id, "instrument": "US500.cash"},
                    "candles": [],
                    "indicators": {},
                    "levels": {},
                    "warnings": [],
                }

        client.app.state.talim_runtime = FakeRuntime()
        r = client.get(
            "/talim/operator/positions/P1/chart?bars=120",
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 200
        assert r.json()["requested"] == {"bars": 120}
        assert calls == [("P1", 120)]

    def test_returns_404_for_closed_position(self, client):
        class FakeRuntime:
            def operator_position_chart(self, *, position_id, bars=240):
                return None

        client.app.state.talim_runtime = FakeRuntime()
        r = client.get(
            "/talim/operator/positions/P1/chart",
            headers={"X-Talim-Secret": SECRET},
        )

        assert r.status_code == 404
