"""Rich-embed formatting for Discord (WP-15).

Pure functions: each takes a domain object and returns a `discord.Embed`.
No network or bot state — trivial to unit test.
"""

from __future__ import annotations

import discord

from talim.models.backtest import BacktestResult
from talim.models.signal import Signal


COLOR_LONG = 0x2ECC71      # green
COLOR_SHORT = 0xE74C3C     # red
COLOR_BACKTEST = 0x3498DB  # blue
COLOR_REGIME = 0xF1C40F    # yellow
COLOR_LOG = 0x95A5A6       # grey


def format_signal_embed(
    signal: Signal,
    atr: float | None = None,
    regime: str | None = None,
    account_balance: float | None = None,
    qty: float = 1.0,
) -> discord.Embed:
    """Format a trade signal as a rich embed for #talim-alerts.

    When `account_balance` is supplied (WP-24), the embed also shows the
    projected dollar risk/reward and what fraction of the account that is.
    """
    color = COLOR_LONG if signal.side == "long" else COLOR_SHORT
    title = f"{signal.side.upper()} {signal.instrument} — {signal.strategy}"
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Entry", value=f"{signal.entry_price:.2f}", inline=True)
    embed.add_field(name="Stop", value=f"{signal.stop:.2f}", inline=True)
    embed.add_field(name="Target", value=f"{signal.target:.2f}", inline=True)

    risk = abs(signal.entry_price - signal.stop)
    reward = abs(signal.target - signal.entry_price)
    rr = (reward / risk) if risk > 0 else 0.0
    embed.add_field(name="R:R", value=f"{rr:.2f}", inline=True)

    regime_label = signal.regime_context or regime or "—"
    embed.add_field(name="Regime", value=regime_label, inline=True)
    if atr is not None:
        embed.add_field(name="ATR", value=f"{atr:.2f}", inline=True)

    if account_balance is not None and account_balance > 0:
        risk_dollars = qty * risk
        reward_dollars = qty * reward
        risk_pct = risk_dollars / account_balance * 100.0
        reward_pct = reward_dollars / account_balance * 100.0
        embed.add_field(
            name="Risk $",
            value=f"{risk_dollars:.2f} ({risk_pct:.2f}%)",
            inline=True,
        )
        embed.add_field(
            name="Reward $",
            value=f"{reward_dollars:.2f} ({reward_pct:.2f}%)",
            inline=True,
        )

    if signal.rationale:
        embed.add_field(name="Rationale", value=signal.rationale, inline=False)
    embed.set_footer(text="React ✅ to approve, ❌ to reject")
    return embed


def format_backtest_embed(results: list[BacktestResult]) -> discord.Embed:
    """Format a list of backtest results (sorted best-first) as an embed."""
    if not results:
        return discord.Embed(
            title="Backtest results",
            description="No results.",
            color=COLOR_BACKTEST,
        )

    best = results[0]
    embed = discord.Embed(
        title=f"Backtest — {best.strategy_name}",
        description=f"{len(results)} variant(s) compared",
        color=COLOR_BACKTEST,
    )
    for i, r in enumerate(results, 1):
        params = ", ".join(f"{k}={v}" for k, v in r.param_variant.items()) or "default"
        value = (
            f"sharpe **{r.sharpe_ratio:.2f}** · "
            f"net {r.net_pnl:.2f} · "
            f"dd {r.max_drawdown:.2f} · "
            f"win {r.win_rate:.0%} · "
            f"trades {r.total_trades}"
        )
        embed.add_field(name=f"#{i}: {params}", value=value, inline=False)
    return embed


def format_regime_change_embed(
    new_regime: str,
    prior_regime: str | None,
    atr_ratio: float | None = None,
) -> discord.Embed:
    """Format a regime change announcement."""
    title = f"Regime change → {new_regime}"
    if prior_regime:
        title = f"Regime: {prior_regime} → {new_regime}"
    embed = discord.Embed(title=title, color=COLOR_REGIME)
    if atr_ratio is not None:
        embed.add_field(name="ATR ratio", value=f"{atr_ratio:.2f}", inline=True)
    return embed


def format_log_embed(message: str, level: str = "info") -> discord.Embed:
    """Plain log embed for #talim-log."""
    return discord.Embed(
        title=f"[{level.upper()}]",
        description=message,
        color=COLOR_LOG,
    )
