"""
channels/
---------
Ruby – Multi-Channel Messaging

Adapters for every messaging platform Ruby supports, plus the ChannelManager
that wires them all to Ruby's model router with a single unified interface.

Supported channels
------------------
  WhatsApp  — Meta Cloud API (webhook)
  Telegram  — Bot API (long-polling or webhook)
  Discord   — Gateway + REST (discord.py)
  Slack     — Bolt + Socket Mode
  Signal    — signal-cli JSON-RPC daemon
  Teams     — Microsoft Bot Framework (webhook)
  SMS       — Twilio Messaging API (webhook)

Quick start
-----------
    import asyncio
    from models.router   import ModelRouter
    from channels.manager import ChannelManager

    router = ModelRouter()
    router.authenticate_all()

    manager = ChannelManager(router=router)
    manager.add_channel("telegram", {"mode": "polling"})   # no public URL needed
    manager.add_channel("discord",  {})

    asyncio.run(manager.run())

Per-channel setup instructions are in each adapter's module docstring.

Vault keys (stored with: ruby vault store <key> <value>)
---------------------------------------------------------
  WhatsApp : whatsapp_token, whatsapp_phone_id, whatsapp_verify_token
  Telegram : telegram_bot_token
  Discord  : discord_bot_token
  Slack    : slack_bot_token, slack_app_token
  Signal   : signal_account, signal_socket
  Teams    : teams_app_id, teams_app_password
  SMS      : twilio_account_sid, twilio_auth_token, twilio_from_number
"""

from .base import (
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    OutboundMessage,
    Sender,
    Attachment,
    MessageType,
    OnMessageCallback,
)
from .manager import ChannelManager

# Individual adapters — imported on demand to avoid hard dependency errors
# when optional packages (e.g. discord.py, slack-bolt) are not installed.

__all__ = [
    # Base types
    "ChannelAdapter",
    "ChannelKind",
    "InboundMessage",
    "OutboundMessage",
    "Sender",
    "Attachment",
    "MessageType",
    "OnMessageCallback",
    # Manager
    "ChannelManager",
]
