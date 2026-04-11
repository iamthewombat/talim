"""Stub NanoClaw intent router (WP-16).

Real NanoClaw is a separate codebase. For the PoC we need just enough logic
to decide whether a message should be handled locally (small talk, status
queries that NanoClaw answers itself) or forwarded to Talim (anything that
touches strategies, signals, P&L, backtests).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

import os

import requests

from talim.api.auth import SECRET_HEADER, SECRET_ENV


class Intent(str, Enum):
    LOCAL = "local"
    TALIM = "talim"


# Keywords that route to Talim. Conservative — anything not matching is local.
_TALIM_KEYWORDS = (
    "strategy", "strategies", "signal", "signals", "trade", "trades",
    "position", "positions", "p&l", "pnl", "backtest", "regime",
    "long", "short", "stop", "target", "momentum", "mean-reversion",
)


@dataclass
class RouteResult:
    intent: Intent
    response: str
    forwarded: bool = False


def classify_intent(message: str) -> Intent:
    msg = message.lower()
    if any(k in msg for k in _TALIM_KEYWORDS):
        return Intent.TALIM
    return Intent.LOCAL


def route_message(
    message: str,
    thread_id: str = "nanoclaw-main",
    talim_url: str | None = None,
    secret: str | None = None,
    http_post: Callable | None = None,
) -> RouteResult:
    """Route a message either locally or to the Talim bridge.

    Args:
        message: User message text.
        thread_id: Thread id passed to Talim.
        talim_url: Base URL for the Talim bridge (default env TALIM_BRIDGE_URL).
        secret: Shared secret (default env TALIM_BRIDGE_SECRET).
        http_post: Injection point for tests (callable matching `requests.post`).
    """
    intent = classify_intent(message)
    if intent is Intent.LOCAL:
        return RouteResult(intent=intent, response=_local_reply(message))

    base = talim_url or os.environ.get("TALIM_BRIDGE_URL", "http://talim:8000")
    sec = secret or os.environ.get(SECRET_ENV, "")
    poster = http_post or requests.post

    resp = poster(
        f"{base.rstrip('/')}/talim/converse",
        json={"message": message, "thread_id": thread_id},
        headers={SECRET_HEADER: sec},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return RouteResult(
        intent=intent,
        response=data.get("response_message") or "(no response)",
        forwarded=True,
    )


def _local_reply(message: str) -> str:
    msg = message.lower().strip()
    if any(g in msg for g in ("hi", "hello", "hey")):
        return "Hello! Ask me about your strategies, signals, or P&L."
    if "help" in msg:
        return "I can answer trading questions via Talim, or chat locally."
    return "Acknowledged."
