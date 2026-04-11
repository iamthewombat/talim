"""Shared-secret auth for the Talim bridge (WP-16).

NanoClaw and Talim share a single secret read from `TALIM_BRIDGE_SECRET`.
Requests must include it as `X-Talim-Secret`. Both sides may use this helper.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status

SECRET_HEADER = "X-Talim-Secret"
SECRET_ENV = "TALIM_BRIDGE_SECRET"


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


async def require_secret(
    x_talim_secret: str | None = Header(default=None, alias=SECRET_HEADER),
) -> None:
    """FastAPI dependency that 401s on missing/wrong secret."""
    if not verify_secret(x_talim_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Talim-Secret",
        )
