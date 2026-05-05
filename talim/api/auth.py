"""Auth helpers for the Talim bridge and operator dashboard.

External bridge clients can continue to use the shared secret in
``X-Talim-Secret``. Browser dashboard users can exchange that secret once for
an HttpOnly signed session cookie so the raw bridge secret is not kept in
browser storage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Cookie, Header, HTTPException, Response, status

SECRET_HEADER = "X-Talim-Secret"
SECRET_ENV = "TALIM_BRIDGE_SECRET"
SESSION_COOKIE = "talim_dashboard_session"
SESSION_DAYS_ENV = "TALIM_DASHBOARD_SESSION_DAYS"
DEFAULT_SESSION_DAYS = 30


def get_expected_secret() -> str | None:
    return os.environ.get(SECRET_ENV)


def verify_secret(provided: str | None) -> bool:
    expected = get_expected_secret()
    if not expected:
        # No secret configured → fail closed.
        return False
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)


def _session_key() -> bytes | None:
    secret = get_expected_secret()
    if not secret:
        return None
    return hashlib.sha256(("talim-dashboard-session:" + secret).encode("utf-8")).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _session_days() -> int:
    raw = os.environ.get(SESSION_DAYS_ENV)
    if not raw:
        return DEFAULT_SESSION_DAYS
    try:
        return max(1, min(int(raw), 365))
    except ValueError:
        return DEFAULT_SESSION_DAYS


def session_max_age_seconds() -> int:
    return _session_days() * 24 * 60 * 60


def create_session_token(*, now: int | None = None) -> str:
    key = _session_key()
    if key is None:
        raise RuntimeError(f"{SECRET_ENV} is not configured")
    issued_at = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "v": 1,
        "iat": issued_at,
        "exp": issued_at + session_max_age_seconds(),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def verify_session_token(token: str | None, *, now: int | None = None) -> bool:
    key = _session_key()
    if key is None or not token or "." not in token:
        return False
    payload_b64, sig_b64 = token.rsplit(".", 1)
    expected_sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return False
    if not hmac.compare_digest(expected_sig, actual_sig):
        return False
    try:
        exp = int(payload["exp"])
    except Exception:
        return False
    current = int(now if now is not None else time.time())
    return current <= exp


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(),
        max_age=session_max_age_seconds(),
        httponly=True,
        samesite="lax",
        secure=False,  # Talim dashboard is served locally over HTTP/nginx today.
        path="/talim",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/talim", samesite="lax")


async def require_secret(
    x_talim_secret: str | None = Header(default=None, alias=SECRET_HEADER),
    talim_dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    """FastAPI dependency that 401s on missing/wrong bridge auth."""
    if verify_secret(x_talim_secret) or verify_session_token(talim_dashboard_session):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing Talim auth",
    )
