"""Dashboard session-cookie auth tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from talim.api.auth import create_session_token, verify_session_token
from talim.api.bridge import create_app

SECRET = "operator-secret"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
    app = create_app(
        bridge_message_fn=lambda **_: {},
        resume_fn=lambda **_: {},
        cron_trigger_fn=lambda **_: {},
    )
    return TestClient(app)


def test_dashboard_login_sets_httponly_session_cookie(monkeypatch):
    client = _client(monkeypatch)

    unauth = client.get("/talim/operator/status")
    assert unauth.status_code == 401

    login = client.post("/talim/auth/login", json={"secret": SECRET})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    set_cookie = login.headers["set-cookie"]
    assert "talim_dashboard_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    # The cookie authenticates API calls without re-sending X-Talim-Secret.
    authed = client.get("/talim/operator/status")
    assert authed.status_code == 503


def test_dashboard_login_rejects_bad_secret(monkeypatch):
    client = _client(monkeypatch)

    response = client.post("/talim/auth/login", json={"secret": "wrong"})

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_session_token_expires_and_rotates_with_bridge_secret(monkeypatch):
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
    monkeypatch.setenv("TALIM_DASHBOARD_SESSION_DAYS", "1")

    token = create_session_token(now=1_000)

    assert verify_session_token(token, now=1_000 + 86_400)
    assert not verify_session_token(token, now=1_000 + 86_401)

    monkeypatch.setenv("TALIM_BRIDGE_SECRET", "rotated-secret")
    assert not verify_session_token(token, now=1_000)
