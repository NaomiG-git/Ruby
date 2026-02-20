"""
channels/slack.py
-----------------
Ruby – Slack Channel Adapter

Connects Ruby to Slack using the Slack Bolt for Python framework (Socket Mode
by default — no public URL needed). Ruby responds to DMs and to @mentions in
channels.

Setup
-----
1. Go to https://api.slack.com/apps → Create New App → From Scratch
2. Add OAuth scopes under "OAuth & Permissions":
     Bot Token Scopes: app_mentions:read, channels:history, chat:write,
                       im:history, im:read, im:write, users:read
3. Enable Socket Mode under "Socket Mode" → turn on
4. Generate an App-Level Token (scope: connections:write):
     ruby vault store slack_app_token  xapp-...
5. Install the app to your workspace, copy the Bot User OAuth Token:
     ruby vault store slack_bot_token  xoxb-...

Config keys
-----------
  slack_bot_token  — xoxb-... bot token
  slack_app_token  — xapp-... app-level token (for Socket Mode)

Dependencies
------------
    pip install slack-bolt
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError:
    raise ImportError("slack-bolt required: pip install slack-bolt")

from .base import (
    Attachment,
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger = logging.getLogger("ruby.channels.slack")

SLACK_MAX_LENGTH = 4000


class SlackAdapter(ChannelAdapter):
    """
    Slack adapter for Ruby using Bolt + Socket Mode.

    Socket Mode does not require a public URL — the adapter opens an outbound
    WebSocket to Slack, so it works behind NAT/firewalls.
    """

    kind = ChannelKind.SLACK

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._app:     Optional[App]               = None
        self._handler: Optional[SocketModeHandler] = None
        self._thread:  Optional[threading.Thread]  = None
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._bot_id:  str = ""

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        bot_token = (
            self._vault_get("slack_bot_token")
            or self._config.get("bot_token", "")
        )
        app_token = (
            self._vault_get("slack_app_token")
            or self._config.get("app_token", "")
        )
        if not bot_token or not app_token:
            raise RuntimeError(
                "Slack tokens missing. Store them with:\n"
                "  ruby vault store slack_bot_token xoxb-...\n"
                "  ruby vault store slack_app_token  xapp-..."
            )

        self._loop = asyncio.get_event_loop()

        self._app = App(token=bot_token)

        # Resolve bot user ID for mention detection
        auth = self._app.client.auth_test()
        self._bot_id = auth.get("user_id", "")
        logger.info("[Slack] Connected as bot_id=%s", self._bot_id)

        self._register_events()

        # Run SocketModeHandler in a background thread (it's synchronous internally)
        self._handler = SocketModeHandler(self._app, app_token)
        self._thread  = threading.Thread(target=self._handler.start, daemon=True)
        self._thread.start()

        self._connected = True
        logger.info("[Slack] Socket Mode started.")

    async def disconnect(self) -> None:
        if self._handler:
            try:
                self._handler.close()
            except Exception:
                pass
        self._connected = False
        logger.info("[Slack] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        kwargs: dict = {
            "channel": message.chat_id,
            "text":    message.text[:SLACK_MAX_LENGTH],
        }
        if message.reply_to:
            # reply_to in Slack = thread_ts
            kwargs["thread_ts"] = message.reply_to

        # Run sync Slack call in executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._app.client.chat_postMessage(**kwargs),
        )

    async def send_typing(self, chat_id: str) -> None:
        # Slack does not expose a bot typing API; this is a no-op
        pass

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._app.client.reactions_add(
                channel=chat_id,
                timestamp=message_id,
                name=emoji.strip(":"),
            ),
        )

    # ------------------------------------------------------------------
    # Event registration (Bolt decorators)
    # ------------------------------------------------------------------

    def _register_events(self) -> None:
        app = self._app

        @app.event("message")
        def handle_message(event, say, client):
            # Skip bot messages and message_changed subtypes
            if event.get("bot_id") or event.get("subtype"):
                return

            # Only respond to DMs or if mentioned for channel messages
            channel_type = event.get("channel_type", "")
            text         = event.get("text", "")
            is_dm        = channel_type in ("im", "mpim")
            is_mention   = f"<@{self._bot_id}>" in text

            if not is_dm and not is_mention:
                return

            msg = self._parse_event(event, client)
            if msg:
                asyncio.run_coroutine_threadsafe(self._dispatch(msg), self._loop)

        @app.event("app_mention")
        def handle_mention(event, say, client):
            # app_mention fires for @Ruby mentions — process as a message
            msg = self._parse_event(event, client)
            if msg:
                asyncio.run_coroutine_threadsafe(self._dispatch(msg), self._loop)

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_event(self, event: dict, client) -> Optional[InboundMessage]:
        try:
            user_id    = event.get("user", "")
            channel_id = event.get("channel", "")
            ts         = event.get("ts", "")
            text       = event.get("text", "")
            thread_ts  = event.get("thread_ts")

            # Strip bot mention
            text = text.replace(f"<@{self._bot_id}>", "").strip()

            # Resolve display name
            display_name = ""
            try:
                info = client.users_info(user=user_id)
                profile = info["user"].get("profile", {})
                display_name = profile.get("display_name") or profile.get("real_name", "")
            except Exception:
                pass

            sender = Sender(id=user_id, display_name=display_name)

            attachments: list[Attachment] = []
            for f in event.get("files", []):
                atype = "image" if (f.get("mimetype", "")).startswith("image") else "file"
                attachments.append(Attachment(
                    type=atype,
                    url=f.get("url_private", ""),
                    filename=f.get("name", ""),
                    mime=f.get("mimetype", ""),
                ))

            msg_type = (
                MessageType.IMAGE if attachments and attachments[0].type == "image"
                else MessageType.FILE if attachments
                else MessageType.TEXT
            )

            return InboundMessage(
                channel=ChannelKind.SLACK,
                chat_id=channel_id,
                message_id=ts,
                sender=sender,
                text=text,
                type=msg_type,
                attachments=attachments,
                reply_to=thread_ts,
                raw=event,
            )
        except Exception as exc:
            logger.exception("[Slack] Failed to parse event: %s", exc)
            return None
