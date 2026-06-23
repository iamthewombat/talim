"""Tests for Discord position-lifecycle webhook pushes (opens + close-outs)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from talim.connectors.discord.position_events import (
    CloseoutEvent,
    OpenEvent,
    derive_reason,
    format_closeout_message,
    format_open_message,
    post_closeout,
    post_open,
)


def _closeout(**overrides) -> CloseoutEvent:
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


def _open(**overrides) -> OpenEvent:
    base = dict(
        instrument="AU200.cash",
        side="long",
        strategy="momentum-AU200",
        qty=1.0,
        entry_price=8200.0,
        stop=8180.0,
        target=8260.0,
        regime="momentum",
        atr=12.5,
        entry_time=datetime(2026, 6, 13, 9, 0, tzinfo=timezone.utc),
        order_id="ord-456",
    )
    base.update(overrides)
    return OpenEvent(**base)


class TestCloseoutFormatter:
    def test_profit_uses_green_marker(self):
        msg = format_closeout_message(_closeout(pnl=40.0))
        assert "🟢" in msg
        assert "AU200.cash" in msg
        assert "+40.00" in msg
        assert "ord-123" in msg
        assert "1h30m" in msg

    def test_loss_uses_red_marker(self):
        msg = format_closeout_message(_closeout(pnl=-12.5))
        assert "🔴" in msg
        assert "-12.50" in msg

    def test_unknown_pnl(self):
        msg = format_closeout_message(_closeout(pnl=None, exit_price=None))
        assert "?" in msg

    def test_short_side_in_title(self):
        msg = format_closeout_message(_closeout(side="short"))
        assert "SHORT" in msg


class TestOpenFormatter:
    def test_open_includes_core_fields(self):
        msg = format_open_message(_open())
        assert "🔵" in msg
        assert "LONG AU200.cash" in msg
        assert "momentum-AU200" in msg
        assert "8200.00" in msg
        assert "stop 8180.00" in msg
        assert "target 8260.00" in msg
        assert "ord-456" in msg

    def test_open_computes_rr(self):
        # risk 20, reward 60 → R:R 3.00
        msg = format_open_message(_open())
        assert "R:R 3.00" in msg

    def test_open_zero_risk_no_crash(self):
        msg = format_open_message(_open(stop=0.0))
        assert "R:R 0.00" in msg
        # `_fmt_price` renders 0.0 as "0.00", so just confirm no traceback / output exists.
        assert "stop" in msg

    def test_open_omits_regime_atr_when_absent(self):
        msg = format_open_message(_open(regime=None, atr=None))
        assert "regime" not in msg
        assert "ATR" not in msg


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
        monkeypatch.delenv("TALIM_DISCORD_POSITION_WEBHOOK", raising=False)
        assert post_closeout(_closeout()) is False

    def test_posts_when_env_set(self, monkeypatch):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append({"url": str(request.url), "json": request.read().decode()})
            return httpx.Response(204)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_POSITION_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )

        ok = post_closeout(_closeout(), client=client)
        assert ok is True
        assert len(seen) == 1
        assert "discord.com/api/webhooks/123/abc" in seen[0]["url"]
        assert "Close-out" in seen[0]["json"]

    def test_returns_false_on_non_2xx(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="oops")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_POSITION_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )
        assert post_closeout(_closeout(), client=client) is False

    def test_returns_false_on_exception(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_POSITION_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )
        assert post_closeout(_closeout(), client=client) is False


class TestPostOpen:
    def test_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("TALIM_DISCORD_POSITION_WEBHOOK", raising=False)
        assert post_open(_open()) is False

    def test_posts_when_env_set(self, monkeypatch):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append({"url": str(request.url), "json": request.read().decode()})
            return httpx.Response(204)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv(
            "TALIM_DISCORD_POSITION_WEBHOOK",
            "https://discord.com/api/webhooks/123/abc",
        )

        ok = post_open(_open(), client=client)
        assert ok is True
        assert len(seen) == 1
        assert "**Open**" in seen[0]["json"]
        assert "AU200.cash" in seen[0]["json"]
