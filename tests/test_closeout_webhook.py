"""Tests for the Discord close-out webhook push."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from talim.connectors.discord.closeout import (
    CloseoutEvent,
    derive_reason,
    format_closeout_message,
    post_closeout,
)


def _event(**overrides) -> CloseoutEvent:
    base = dict(
        instrument="AU200.cash",
        side="long",
        strategy="momentum-AU200",
        qty=1.0,
        entry_price=8200.0,
        exit_price=8240.0,
        pnl=40.0,
        entry_time=datetime(2026, 6, 13, 9, 0, tzinfo=timezone.utc),
        exit_time=datetime(2026, 6, 13, 10, 30, tzinfo=timezone.utc),
        order_id="ord-123",
        reason="target",
    )
    base.update(overrides)
    return CloseoutEvent(**base)


class TestFormatter:
    def test_profit_uses_green_marker(self):
        msg = format_closeout_message(_event(pnl=40.0))
        assert "🟢" in msg
        assert "AU200.cash" in msg
        assert "+40.00" in msg
        assert "ord-123" in msg
        assert "1h30m" in msg

    def test_loss_uses_red_marker(self):
        msg = format_closeout_message(_event(pnl=-12.5))
        assert "🔴" in msg
        assert "-12.50" in msg

    def test_unknown_pnl(self):
        msg = format_closeout_message(_event(pnl=None, exit_price=None))
        assert "?" in msg

    def test_short_side_in_title(self):
        msg = format_closeout_message(_event(side="short"))
        assert "SHORT" in msg


class TestDeriveReason:
    def test_long_hits_target(self):
        assert (
            derive_reason(exit_price=8240.0, stop=8180.0, target=8240.0, side="long")
            == "target"
        )

    def test_long_hits_stop(self):
        assert (
            derive_reason(exit_price=8180.0, stop=8180.0, target=8240.0, side="long")
            == "stop"
        )

    def test_short_hits_target(self):
        assert (
            derive_reason(exit_price=8160.0, stop=8240.0, target=8160.0, side="short")
            == "target"
        )

    def test_short_hits_stop(self):
        assert (
            derive_reason(exit_price=8240.0, stop=8240.0, target=8160.0, side="short")
            == "stop"
        )

    def test_between_is_manual(self):
        assert (
            derive_reason(exit_price=8200.0, stop=8180.0, target=8240.0, side="long")
            == "manual"
        )

    def test_missing_stop_or_target(self):
        assert (
            derive_reason(exit_price=8200.0, stop=0.0, target=8240.0, side="long")
            == "exit"
        )


class TestPostCloseout:
    def test_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("TALIM_DISCORD_CLOSEOUT_WEBHOOK", raising=False)
        assert post_closeout(_event()) is False

    def test_posts_when_env_set(self, monkeypatch):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append({"url": str(request.url), "json": request.read().decode()})
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        monkeypatch.setenv(
            "TALIM_DISCORD_CLOSEOUT_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )

        ok = post_closeout(_event(), client=client)
        assert ok is True
        assert len(seen) == 1
        assert "discord.com/api/webhooks/123/abc" in seen[0]["url"]
        assert "Close-out" in seen[0]["json"]

    def test_returns_false_on_non_2xx(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="oops")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_CLOSEOUT_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )
        assert post_closeout(_event(), client=client) is False

    def test_returns_false_on_exception(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_CLOSEOUT_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )
        assert post_closeout(_event(), client=client) is False
