"""Tests for the Discord connector (WP-15)."""

import discord
import pytest

from talim.connectors.discord.formatter import (
    COLOR_LONG,
    COLOR_SHORT,
    format_backtest_embed,
    format_log_embed,
    format_regime_change_embed,
    format_signal_embed,
)
from talim.connectors.discord.reactions import (
    APPROVE_EMOJI,
    REJECT_EMOJI,
    ReactionHandler,
    interpret_reaction,
)
from talim.models.backtest import BacktestResult
from talim.models.signal import Signal


def _signal(side: str = "long") -> Signal:
    return Signal(
        instrument="ES", strategy="momentum-ES", side=side,
        entry_price=5400.0, stop=5380.0, target=5440.0,
        rationale="EMA cross", regime_context="momentum",
    )


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

class TestFormatter:
    def test_long_signal_embed(self):
        e = format_signal_embed(_signal("long"), atr=12.5)
        assert isinstance(e, discord.Embed)
        assert e.color.value == COLOR_LONG
        assert "LONG ES" in e.title
        names = [f.name for f in e.fields]
        assert "Entry" in names and "Stop" in names and "Target" in names
        assert "R:R" in names
        assert "ATR" in names

    def test_short_signal_color(self):
        e = format_signal_embed(_signal("short"))
        assert e.color.value == COLOR_SHORT

    def test_signal_pnl_projection(self):
        # WP-24: when account_balance is supplied, embed shows risk/reward $.
        e = format_signal_embed(
            _signal("long"), account_balance=100_000.0, qty=2.0
        )
        names = [f.name for f in e.fields]
        assert "Risk $" in names and "Reward $" in names
        risk_val = next(f.value for f in e.fields if f.name == "Risk $")
        reward_val = next(f.value for f in e.fields if f.name == "Reward $")
        # entry-stop=20, qty=2 → risk_$ = 40 → 0.04% of 100k
        assert "40.00" in risk_val and "0.04%" in risk_val
        # target-entry=40, qty=2 → reward_$ = 80 → 0.08% of 100k
        assert "80.00" in reward_val and "0.08%" in reward_val

    def test_signal_rr_calculation(self):
        e = format_signal_embed(_signal("long"))
        rr_field = next(f for f in e.fields if f.name == "R:R")
        # risk=20, reward=40 → 2.00
        assert rr_field.value == "2.00"

    def test_backtest_embed_lists_all(self):
        results = [
            BacktestResult("momentum-ES", 200.0, 1.5, -50.0, 0.6, 10, {"ema_fast_period": 5}),
            BacktestResult("momentum-ES", 100.0, 0.9, -80.0, 0.4, 8, {"ema_fast_period": 8}),
        ]
        e = format_backtest_embed(results)
        assert "2 variant(s)" in e.description
        assert len(e.fields) == 2
        assert "ema_fast_period=5" in e.fields[0].name

    def test_backtest_empty(self):
        e = format_backtest_embed([])
        assert "No results" in e.description

    def test_regime_change_with_prior(self):
        e = format_regime_change_embed("momentum", "mean_reversion", atr_ratio=1.3)
        assert "mean_reversion" in e.title and "momentum" in e.title
        assert any(f.name == "ATR ratio" for f in e.fields)

    def test_regime_change_without_prior(self):
        e = format_regime_change_embed("high_vol", None)
        assert "high_vol" in e.title

    def test_log_embed(self):
        e = format_log_embed("scanner finished", level="info")
        assert "INFO" in e.title
        assert e.description == "scanner finished"


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

class TestInterpretReaction:
    def test_approve(self):
        assert interpret_reaction(APPROVE_EMOJI) is True

    def test_reject(self):
        assert interpret_reaction(REJECT_EMOJI) is False

    def test_other(self):
        assert interpret_reaction("👀") is None
        assert interpret_reaction("") is None


class TestReactionHandler:
    def test_register_and_lookup(self):
        h = ReactionHandler(resume_callback=lambda *a, **k: None)
        h.register(message_id=42, thread_id="cron-1")
        assert h.get_thread(42) == "cron-1"

    def test_approve_invokes_callback(self):
        calls = []
        h = ReactionHandler(resume_callback=lambda tid, ok: calls.append((tid, ok)))
        h.register(42, "cron-1")
        assert h.handle_reaction(42, APPROVE_EMOJI) is True
        assert calls == [("cron-1", True)]

    def test_reject_invokes_callback(self):
        calls = []
        h = ReactionHandler(resume_callback=lambda tid, ok: calls.append((tid, ok)))
        h.register(42, "cron-1")
        assert h.handle_reaction(42, REJECT_EMOJI) is True
        assert calls == [("cron-1", False)]

    def test_unknown_emoji_no_op(self):
        calls = []
        h = ReactionHandler(resume_callback=lambda *a: calls.append(a))
        h.register(42, "cron-1")
        assert h.handle_reaction(42, "🚀") is False
        assert calls == []
        # Message still registered.
        assert h.get_thread(42) == "cron-1"

    def test_unknown_message_no_op(self):
        calls = []
        h = ReactionHandler(resume_callback=lambda *a: calls.append(a))
        assert h.handle_reaction(99, APPROVE_EMOJI) is False
        assert calls == []

    def test_message_consumed_after_resume(self):
        h = ReactionHandler(resume_callback=lambda *a, **k: None)
        h.register(42, "cron-1")
        h.handle_reaction(42, APPROVE_EMOJI)
        assert h.get_thread(42) is None


# ---------------------------------------------------------------------------
# Bot construction (no network)
# ---------------------------------------------------------------------------

class TestBotConstruction:
    def test_constructs_with_explicit_ids(self):
        from talim.connectors.discord.bot import TalimDiscordBot
        bot = TalimDiscordBot(
            alerts_channel_id=1, chat_channel_id=2, log_channel_id=3,
        )
        assert bot.alerts_channel_id == 1
        assert bot.chat_channel_id == 2
        assert bot.log_channel_id == 3

    def test_reads_channels_from_env(self, monkeypatch):
        monkeypatch.setenv("TALIM_DISCORD_ALERTS_CHANNEL", "111")
        monkeypatch.setenv("TALIM_DISCORD_CHAT_CHANNEL", "222")
        monkeypatch.setenv("TALIM_DISCORD_LOG_CHANNEL", "333")
        from talim.connectors.discord.bot import TalimDiscordBot
        bot = TalimDiscordBot()
        assert bot.alerts_channel_id == 111
        assert bot.chat_channel_id == 222
        assert bot.log_channel_id == 333
