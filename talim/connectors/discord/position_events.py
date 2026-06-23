"""Position lifecycle pushes to Discord via webhook.

Fires immediately from the execute node when a position is opened or
closed, so the operator sees the trade without waiting for the next cron
poll. Uses a plain Discord webhook URL (no bot token required) read from
`TALIM_DISCORD_POSITION_WEBHOOK`. If the env var is unset, the helpers
no-op so unit tests and unconfigured deployments don't break.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("talim.discord.position_events")

_WEBHOOK_ENV = "TALIM_DISCORD_POSITION_WEBHOOK"
_HTTP_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class CloseoutEvent:
    instrument: str
    side: str
    strategy: str
    qty: float
    entry_price: float
    exit_price: float | None
    pnl: float | None
    entry_time: datetime | None
    exit_time: datetime
    order_id: str
    reason: str  # "target" | "stop" | "manual" | "exit"


@dataclass(slots=True)
class OpenEvent:
    instrument: str
    side: str
    strategy: str
    qty: float
    entry_price: float
    stop: float
    target: float
    regime: str | None
    atr: float | None
    entry_time: datetime
    order_id: str


def _fmt_price(p: float | None) -> str:
    return f"{p:.2f}" if isinstance(p, (int, float)) else "?"


def _fmt_hold(entry: datetime | None, exit_: datetime) -> str:
    if entry is None:
        return "?"
    delta = exit_ - entry
    total = int(delta.total_seconds())
    if total < 0:
        return "?"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def format_closeout_message(event: CloseoutEvent) -> str:
    pnl_str = f"{event.pnl:+.2f}" if isinstance(event.pnl, (int, float)) else "?"
    emoji = "🟢" if isinstance(event.pnl, (int, float)) and event.pnl >= 0 else "🔴"
    lines = [
        f"{emoji} **Close-out** — {event.side.upper()} {event.instrument} ({event.strategy})",
        f"entry {_fmt_price(event.entry_price)} → exit {_fmt_price(event.exit_price)}  "
        f"qty {event.qty:g}",
        f"P&L {pnl_str}  ·  hold {_fmt_hold(event.entry_time, event.exit_time)}  "
        f"·  reason {event.reason}",
        f"order `{event.order_id}`",
    ]
    return "\n".join(lines)


def format_open_message(event: OpenEvent) -> str:
    risk = abs(event.entry_price - event.stop) if event.stop > 0 else 0.0
    reward = abs(event.target - event.entry_price) if event.target > 0 else 0.0
    rr = (reward / risk) if risk > 0 else 0.0
    third_bits = []
    if event.regime:
        third_bits.append(f"regime: {event.regime}")
    if isinstance(event.atr, (int, float)):
        third_bits.append(f"ATR {event.atr:.2f}")
    third_line = "  ·  ".join(third_bits) if third_bits else ""

    lines = [
        f"🔵 **Open** — {event.side.upper()} {event.instrument} ({event.strategy})",
        f"entry {_fmt_price(event.entry_price)}  qty {event.qty:g}",
        f"stop {_fmt_price(event.stop)} / target {_fmt_price(event.target)}  R:R {rr:.2f}",
    ]
    if third_line:
        lines.append(third_line)
    lines.append(f"order `{event.order_id}`")
    return "\n".join(lines)


def _webhook_url() -> str | None:
    url = os.environ.get(_WEBHOOK_ENV)
    return url.strip() if url else None


def _post_content(content: str, *, client: httpx.Client | None = None) -> bool:
    url = _webhook_url()
    if not url:
        return False

    payload = {"content": content, "allowed_mentions": {"parse": []}}

    try:
        if client is None:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as c:
                resp = c.post(url, json=payload)
        else:
            resp = client.post(url, json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("position webhook request failed")
        return False

    if 200 <= resp.status_code < 300:
        return True
    logger.warning(
        "position webhook returned %s: %s", resp.status_code, resp.text[:200]
    )
    return False


def post_closeout(event: CloseoutEvent, *, client: httpx.Client | None = None) -> bool:
    """POST a close-out message to the configured Discord webhook.

    Returns True on a 2xx response. Returns False (without raising) if the
    webhook isn't configured or the request fails — these posts must never
    break the execute path.
    """
    return _post_content(format_closeout_message(event), client=client)


def post_open(event: OpenEvent, *, client: httpx.Client | None = None) -> bool:
    """POST a position-open message to the configured Discord webhook."""
    return _post_content(format_open_message(event), client=client)


def derive_reason(*, exit_price: float | None, stop: float, target: float, side: str) -> str:
    """Best-effort reason classification from exit price vs stop/target."""
    if exit_price is None or stop <= 0 or target <= 0:
        return "exit"
    if side == "long":
        if exit_price <= stop:
            return "stop"
        if exit_price >= target:
            return "target"
    else:
        if exit_price >= stop:
            return "stop"
        if exit_price <= target:
            return "target"
    return "manual"


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
