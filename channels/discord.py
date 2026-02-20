"""
channels/discord.py
-------------------
Ruby – Discord Channel Adapter

Connects Ruby to Discord via the Discord Gateway (WebSocket) and REST API
using a bot token. Ruby responds to DMs and to messages in channels/guilds
where she's been granted access.

Setup
-----
1. Go to https://discord.com/developers/applications → New Application → Bot
2. Enable "Message Content Intent" under Bot → Privileged Gateway Intents
3. Copy the bot token:
     ruby vault store discord_bot_token <token>
4. Invite the bot to your server with scopes: bot + applications.commands
   Permissions needed: Read Messages, Send Messages, Read Message History

Config keys
-----------
  discord_bot_token   — bot token from Discord Developer Portal
  discord_dm_only     — "true" to respond in DMs only (default: false)
  discord_prefix      — optional command prefix (e.g. "!ruby "); default: mention

Dependencies
------------
    pip install discord.py
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    import discord
    from discord.ext import commands
except ImportError:
    raise ImportError("discord.py required: pip install discord.py")

from .base import (
    Attachment,
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger = logging.getLogger("ruby.channels.discord")

# Discord message length limit
DISCORD_MAX_LENGTH = 2000


class DiscordAdapter(ChannelAdapter):
    """
    Discord bot adapter for Ruby.

    Uses discord.py's async client. Ruby is activated by:
      - DMs (always)
      - Direct mentions (@Ruby ...) in guild channels
      - Configured prefix (e.g. "!ruby ...")
    """

    kind = ChannelKind.DISCORD

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._client:   Optional[discord.Client] = None
        self._task:     Optional[asyncio.Task]   = None
        self._token:    str = ""
        self._dm_only:  bool = False
        self._prefix:   str = ""

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._token = (
            self._vault_get("discord_bot_token")
            or self._config.get("bot_token", "")
        )
        if not self._token:
            raise RuntimeError(
                "Discord bot token missing.\n"
                "  ruby vault store discord_bot_token <token>"
            )
        self._dm_only = str(self._config.get("dm_only", "false")).lower() == "true"
        self._prefix  = self._config.get("prefix", "")

        intents = discord.Intents.default()
        intents.message_content = True   # requires privileged intent in Dev Portal
        intents.dm_messages     = True

        self._client = discord.Client(intents=intents)
        self._register_events()

        # Run the client in a background task
        self._task = asyncio.create_task(self._client.start(self._token))
        # Wait briefly to confirm connection
        await asyncio.sleep(2)
        self._connected = True
        logger.info("[Discord] Bot connected.")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
        self._connected = False
        logger.info("[Discord] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        channel = self._client.get_channel(int(message.chat_id))
        if channel is None:
            # Try as user DM
            try:
                user = await self._client.fetch_user(int(message.chat_id))
                channel = await user.create_dm()
            except Exception:
                logger.error("[Discord] Cannot find channel/user: %s", message.chat_id)
                return

        # Split long messages
        text = message.text
        while text:
            chunk  = text[:DISCORD_MAX_LENGTH]
            text   = text[DISCORD_MAX_LENGTH:]
            kwargs = {}
            if message.reply_to and not text:  # reply only on last chunk
                try:
                    msg_obj = await channel.fetch_message(int(message.reply_to))
                    await msg_obj.reply(chunk, **kwargs)
                    continue
                except Exception:
                    pass
            await channel.send(chunk)

    async def send_typing(self, chat_id: str) -> None:
        channel = self._client.get_channel(int(chat_id))
        if channel:
            async with channel.typing():
                await asyncio.sleep(1)

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        channel = self._client.get_channel(int(chat_id))
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.add_reaction(emoji)
            except Exception as exc:
                logger.warning("[Discord] React failed: %s", exc)

    # ------------------------------------------------------------------
    # Event registration
    # ------------------------------------------------------------------

    def _register_events(self) -> None:
        @self._client.event
        async def on_ready():
            logger.info("[Discord] Logged in as %s (id=%s)", self._client.user, self._client.user.id)

        @self._client.event
        async def on_message(discord_msg: discord.Message):
            # Ignore own messages
            if discord_msg.author == self._client.user:
                return

            is_dm      = isinstance(discord_msg.channel, discord.DMChannel)
            mentioned  = self._client.user in discord_msg.mentions
            has_prefix = self._prefix and discord_msg.content.startswith(self._prefix)

            # Decide whether to process
            if not is_dm and not mentioned and not has_prefix:
                return
            if self._dm_only and not is_dm:
                return

            msg = self._parse_message(discord_msg)
            if msg:
                asyncio.create_task(self._dispatch(msg))

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_message(self, discord_msg: discord.Message) -> Optional[InboundMessage]:
        try:
            text = discord_msg.content or ""

            # Strip bot mention from text
            if self._client.user:
                text = text.replace(f"<@{self._client.user.id}>", "").strip()
                text = text.replace(f"<@!{self._client.user.id}>", "").strip()

            # Strip prefix
            if self._prefix and text.startswith(self._prefix):
                text = text[len(self._prefix):].strip()

            sender = Sender(
                id=str(discord_msg.author.id),
                display_name=discord_msg.author.display_name,
                username=str(discord_msg.author),
                is_bot=discord_msg.author.bot,
            )

            attachments: list[Attachment] = []
            for att in discord_msg.attachments:
                atype = "image" if att.content_type and att.content_type.startswith("image") else "file"
                attachments.append(Attachment(
                    type=att.content_type or "file",
                    url=att.url,
                    filename=att.filename,
                    mime=att.content_type or "",
                ))

            chat_id   = str(discord_msg.channel.id)
            msg_id    = str(discord_msg.id)
            reply_to  = str(discord_msg.reference.message_id) if discord_msg.reference else None
            msg_type  = MessageType.IMAGE if attachments and "image" in attachments[0].type else (
                        MessageType.FILE  if attachments else MessageType.TEXT)

            return InboundMessage(
                channel=ChannelKind.DISCORD,
                chat_id=chat_id,
                message_id=msg_id,
                sender=sender,
                text=text,
                type=msg_type,
                attachments=attachments,
                reply_to=reply_to,
                raw=discord_msg,
            )
        except Exception as exc:
            logger.exception("[Discord] Failed to parse message: %s", exc)
            return None
