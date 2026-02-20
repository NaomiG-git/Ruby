"""
channels/base.py
----------------
Ruby – Channel Adapter Base Class

All messaging channel adapters (WhatsApp, Telegram, Discord, Slack, Signal,
Teams, SMS) inherit from ChannelAdapter and implement the same interface.
The ChannelManager uses this interface to route inbound messages to Ruby's
model router and send replies back over the correct channel.

Lifecycle
---------
1. adapter = WhatsAppAdapter(config, vault, router)
2. adapter.connect()          # authenticate + open session
3. # ... Ruby receives InboundMessage objects via adapter.on_message callback
4. adapter.send(chat_id, text)
5. adapter.disconnect()

Message format
--------------
All adapters normalise inbound messages to InboundMessage dataclasses and
produce OutboundMessage dataclasses for sends — so the router never sees
channel-specific wire formats.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("ruby.channels")


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class ChannelKind(str, Enum):
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    DISCORD  = "discord"
    SLACK    = "slack"
    SIGNAL   = "signal"
    TEAMS    = "teams"
    SMS      = "sms"


class MessageType(str, Enum):
    TEXT     = "text"
    IMAGE    = "image"
    FILE     = "file"
    AUDIO    = "audio"
    VIDEO    = "video"
    REACTION = "reaction"
    SYSTEM   = "system"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Sender:
    id:           str                   # channel-scoped unique user ID
    display_name: str = ""
    username:     str = ""
    is_bot:       bool = False


@dataclass
class Attachment:
    type:     str           # "image" | "file" | "audio" | "video"
    url:      str = ""
    filename: str = ""
    mime:     str = ""
    data:     Optional[bytes] = None    # raw bytes if already fetched


@dataclass
class InboundMessage:
    channel:     ChannelKind
    chat_id:     str                    # DM or group/channel ID
    message_id:  str
    sender:      Sender
    text:        str = ""
    type:        MessageType = MessageType.TEXT
    attachments: list[Attachment] = field(default_factory=list)
    raw:         Any = None             # original channel payload (for debugging)
    reply_to:    Optional[str] = None   # message_id being replied to


@dataclass
class OutboundMessage:
    chat_id:      str
    text:         str
    reply_to:     Optional[str] = None  # message_id to reply to
    attachments:  list[Attachment] = field(default_factory=list)
    parse_mode:   str = "markdown"      # "markdown" | "html" | "plain"


# ---------------------------------------------------------------------------
# Callback type aliases
# ---------------------------------------------------------------------------

# async def on_message(msg: InboundMessage) -> None
OnMessageCallback = Callable[[InboundMessage], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# ChannelAdapter — abstract base
# ---------------------------------------------------------------------------

class ChannelAdapter(ABC):
    """
    Abstract base for all Ruby channel adapters.

    Subclasses must implement:
      connect()    — authenticate and start listening
      disconnect() — gracefully shut down
      send()       — send a message to a chat
      kind         — ChannelKind property

    They call self._dispatch(msg) whenever an inbound message arrives.
    """

    def __init__(
        self,
        config: dict,
        vault=None,
        on_message: Optional[OnMessageCallback] = None,
    ):
        """
        Parameters
        ----------
        config : dict
            Channel-specific config (credentials, webhook port, etc.).
            Sensitive values are retrieved from the vault rather than stored here.
        vault : Vault | None
            Ruby vault for credential retrieval.
        on_message : async callable | None
            Coroutine called for every inbound message.
        """
        self._config = config
        self._vault  = vault or self._default_vault()
        self._on_message: Optional[OnMessageCallback] = on_message
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def kind(self) -> ChannelKind:
        """The channel this adapter handles."""

    @abstractmethod
    async def connect(self) -> None:
        """Authenticate with the channel and start listening for messages."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully stop the adapter and release resources."""

    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """
        Send *message* over the channel.

        Parameters
        ----------
        message : OutboundMessage
            Normalised outbound message.
        """

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    async def send_typing(self, chat_id: str) -> None:
        """Show a typing indicator in the chat, if the channel supports it."""

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        """Add a reaction to a message, if the channel supports it."""

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """Delete a previously sent message, if the channel supports it."""

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def set_on_message(self, callback: OnMessageCallback) -> None:
        """Register (or replace) the inbound message callback."""
        self._on_message = callback

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Call the on_message callback. Logs errors without crashing the adapter."""
        if self._on_message is None:
            logger.warning("[%s] Inbound message received but no on_message handler set.", self.kind.value)
            return
        try:
            await self._on_message(msg)
        except Exception as exc:
            logger.exception("[%s] on_message handler raised: %s", self.kind.value, exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()

    def _vault_get(self, key: str, fallback: Optional[str] = None) -> Optional[str]:
        """Retrieve a value from the vault, returning fallback if not found."""
        try:
            return self._vault.retrieve(key)
        except KeyError:
            return fallback

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<{self.__class__.__name__} kind={self.kind.value} {status}>"
