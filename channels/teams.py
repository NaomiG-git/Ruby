"""
channels/teams.py
-----------------
Ruby – Microsoft Teams Channel Adapter

Connects Ruby to Microsoft Teams as a bot using the Bot Framework SDK. Inbound
activities (messages) arrive via a webhook endpoint; outbound messages are sent
via the Bot Connector REST API.

Setup
-----
1. Register a Bot in https://dev.botframework.com (or Azure Bot Service)
2. Note the App ID and App Password:
     ruby vault store teams_app_id       <Microsoft App ID>
     ruby vault store teams_app_password <Microsoft App Password>
3. Set your messaging endpoint (ngrok / Azure URL) in the Bot Framework portal:
     https://your-host/api/messages
4. Add the bot to a Teams team, or start a DM with it.

Config keys
-----------
  teams_app_id       — Microsoft App ID (GUID)
  teams_app_password — Bot Framework app password / client secret
  teams_webhook_port — local port for the HTTP listener (default: 3978)
  teams_webhook_path — URL path for the endpoint (default: /api/messages)

Dependencies
------------
    pip install botframework-connector aiohttp
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

try:
    from aiohttp import web
    import httpx
except ImportError:
    raise ImportError("aiohttp and httpx required: pip install aiohttp httpx")

from .base import (
    Attachment,
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger = logging.getLogger("ruby.channels.teams")

# Bot Connector service login URL (global)
LOGIN_URL    = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
CONNECTOR_URL= "https://smba.trafficmanager.net/apis"


class TeamsAdapter(ChannelAdapter):
    """
    Microsoft Teams bot adapter for Ruby.

    Hosts a lightweight aiohttp webhook server. When Teams sends an Activity,
    the adapter validates the JWT, translates the Activity to an InboundMessage,
    and calls the on_message handler. Replies are sent back via Bot Connector.
    """

    kind = ChannelKind.TEAMS

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._app_id:       str = ""
        self._app_password: str = ""
        self._access_token: str = ""
        self._token_expiry: float = 0.0
        self._runner:       Optional[web.AppRunner] = None

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._app_id = (
            self._vault_get("teams_app_id")
            or self._config.get("app_id", "")
        )
        self._app_password = (
            self._vault_get("teams_app_password")
            or self._config.get("app_password", "")
        )
        if not self._app_id or not self._app_password:
            raise RuntimeError(
                "Teams credentials missing.\n"
                "  ruby vault store teams_app_id       <App ID>\n"
                "  ruby vault store teams_app_password <App Password>"
            )

        port = int(self._config.get("webhook_port", 3978))
        path = self._config.get("webhook_path", "/api/messages")

        app = web.Application()
        app.router.add_post(path, self._handle_activity)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()

        await self._refresh_token()
        self._connected = True
        logger.info("[Teams] Webhook listening on port %d%s", port, path)

    async def disconnect(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._connected = False
        logger.info("[Teams] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        # chat_id is encoded as "<service_url>|<conversation_id>"
        parts = message.chat_id.split("|", 1)
        if len(parts) != 2:
            logger.error("[Teams] Invalid chat_id format: %s", message.chat_id)
            return

        service_url, conversation_id = parts
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"

        activity: dict = {
            "type":         "message",
            "from":         {"id": self._app_id},
            "conversation": {"id": conversation_id},
            "text":         message.text,
            "textFormat":   "markdown",
        }
        if message.reply_to:
            activity["replyToId"] = message.reply_to

        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=activity,
            )
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Webhook handler
    # ------------------------------------------------------------------

    async def _handle_activity(self, request: web.Request) -> web.Response:
        # TODO: validate JWT from Authorization header in production
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        msg = self._parse_activity(body)
        if msg:
            asyncio.create_task(self._dispatch(msg))

        return web.Response(text="OK")

    # ------------------------------------------------------------------
    # Activity parsing
    # ------------------------------------------------------------------

    def _parse_activity(self, activity: dict) -> Optional[InboundMessage]:
        try:
            if activity.get("type") != "message":
                return None

            service_url   = activity.get("serviceUrl", CONNECTOR_URL)
            conversation  = activity.get("conversation", {})
            conv_id       = conversation.get("id", "")
            msg_id        = activity.get("id", "")
            from_          = activity.get("from", {})
            text          = activity.get("text", "") or ""

            sender = Sender(
                id=from_.get("id", ""),
                display_name=from_.get("name", ""),
            )

            attachments: list[Attachment] = []
            for att in activity.get("attachments", []) or []:
                content_type = att.get("contentType", "")
                url          = att.get("contentUrl", "")
                name         = att.get("name", "")
                atype = "image" if content_type.startswith("image") else "file"
                attachments.append(Attachment(type=atype, url=url, filename=name, mime=content_type))

            msg_type = (
                MessageType.IMAGE if attachments and attachments[0].type == "image"
                else MessageType.FILE if attachments
                else MessageType.TEXT
            )

            # Encode service_url into chat_id so we can reply correctly
            chat_id = f"{service_url}|{conv_id}"

            return InboundMessage(
                channel=ChannelKind.TEAMS,
                chat_id=chat_id,
                message_id=msg_id,
                sender=sender,
                text=text,
                type=msg_type,
                attachments=attachments,
                raw=activity,
            )
        except Exception as exc:
            logger.exception("[Teams] Failed to parse activity: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        import time
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        await self._refresh_token()
        return self._access_token

    async def _refresh_token(self) -> None:
        import time
        data = {
            "grant_type":    "client_credentials",
            "client_id":     self._app_id,
            "client_secret": self._app_password,
            "scope":         "https://api.botframework.com/.default",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(LOGIN_URL, data=data)
            resp.raise_for_status()
            token_data = resp.json()
            self._access_token = token_data["access_token"]
            self._token_expiry = time.time() + token_data.get("expires_in", 3600)
        logger.debug("[Teams] Access token refreshed.")
