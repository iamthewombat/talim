"""Discord bot wrapper (WP-15).

A thin shell over discord.py that:
  • listens on the configured chat channel and forwards messages to a
    callback (typically `bridge_message` from talim.app.entrypoints),
  • exposes `post_alert`, `post_log`, `post_chat` helpers for nodes to push
    embeds into the right channel,
  • watches reactions on alert messages and routes them through a
    `ReactionHandler` for HITL approval.

Channel ids and the bot token are read from environment variables:
  TALIM_DISCORD_TOKEN
  TALIM_DISCORD_ALERTS_CHANNEL
  TALIM_DISCORD_CHAT_CHANNEL
  TALIM_DISCORD_LOG_CHANNEL
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

import discord

from talim.connectors.discord.reactions import ReactionHandler

logger = logging.getLogger("talim.discord.bot")


MessageCallback = Callable[[str, str], Awaitable[str | None]]
"""(thread_id, message) → optional reply text."""


class TalimDiscordBot(discord.Client):
    def __init__(
        self,
        *,
        on_chat_message: MessageCallback | None = None,
        reaction_handler: ReactionHandler | None = None,
        alerts_channel_id: int | None = None,
        chat_channel_id: int | None = None,
        log_channel_id: int | None = None,
        intents: discord.Intents | None = None,
    ) -> None:
        if intents is None:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.reactions = True
        super().__init__(intents=intents)

        self.on_chat_message = on_chat_message
        self.reactions = reaction_handler

        self.alerts_channel_id = alerts_channel_id or _env_int("TALIM_DISCORD_ALERTS_CHANNEL")
        self.chat_channel_id = chat_channel_id or _env_int("TALIM_DISCORD_CHAT_CHANNEL")
        self.log_channel_id = log_channel_id or _env_int("TALIM_DISCORD_LOG_CHANNEL")

    # ------------------------------------------------------------------
    # discord.py event hooks
    # ------------------------------------------------------------------
    async def on_ready(self) -> None:  # pragma: no cover
        logger.info("Discord bot logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:  # pragma: no cover
        if message.author == self.user:
            return
        if self.chat_channel_id and message.channel.id != self.chat_channel_id:
            return
        if self.on_chat_message is None:
            return
        thread_id = f"discord-{message.channel.id}"
        reply = await self.on_chat_message(thread_id, message.content)
        if reply:
            await message.channel.send(reply)

    async def on_raw_reaction_add(  # pragma: no cover
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if self.reactions is None:
            return
        if payload.user_id == (self.user.id if self.user else None):
            return
        self.reactions.handle_reaction(payload.message_id, str(payload.emoji))

    # ------------------------------------------------------------------
    # Outbound posting helpers
    # ------------------------------------------------------------------
    async def post_alert(self, embed: discord.Embed) -> int | None:  # pragma: no cover
        return await self._post_embed(self.alerts_channel_id, embed)

    async def post_chat(self, content: str) -> int | None:  # pragma: no cover
        return await self._post_text(self.chat_channel_id, content)

    async def post_log(self, embed: discord.Embed) -> int | None:  # pragma: no cover
        return await self._post_embed(self.log_channel_id, embed)

    async def _post_embed(  # pragma: no cover
        self, channel_id: int | None, embed: discord.Embed
    ) -> int | None:
        if channel_id is None:
            logger.warning("post_embed: no channel configured")
            return None
        channel = self.get_channel(channel_id)
        if channel is None:
            logger.warning("post_embed: channel %s not found", channel_id)
            return None
        msg = await channel.send(embed=embed)
        return msg.id

    async def _post_text(  # pragma: no cover
        self, channel_id: int | None, content: str
    ) -> int | None:
        if channel_id is None:
            return None
        channel = self.get_channel(channel_id)
        if channel is None:
            return None
        msg = await channel.send(content)
        return msg.id


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("env var %s is not an int: %r", name, raw)
        return None


def run_bot() -> None:  # pragma: no cover
    """Entrypoint used by deployment to start the bot."""
    token = os.environ.get("TALIM_DISCORD_TOKEN")
    if not token:
        raise RuntimeError("TALIM_DISCORD_TOKEN not set")
    bot = TalimDiscordBot()
    bot.run(token)
