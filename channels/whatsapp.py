"""
channels/whatsapp.py
--------------------
Ruby – WhatsApp Channel Adapter

Connects Ruby to WhatsApp using the official Meta Cloud API (WhatsApp Business
Platform). Inbound messages arrive via a webhook; outbound messages are sent
via HTTPS to the Cloud API.

Setup
-----
1. Create a Meta App at https://developers.facebook.com
2. Add the WhatsApp product, pick a phone number, get a permanent token:
     ruby vault store whatsapp_token <token>
     ruby vault store whatsapp_phone_id <phone_number_id>
3. Set your webhook URL (ngrok / public server) and verify token:
     ruby vault store whatsapp_verify_token <any_secret_string>
4. Subscribe to the `messages` webhook field.

Config keys (pass in config dict or stored in vault)
----------------------------------------------------
  whatsapp_token        — permanent access token (Meta)
  whatsapp_phone_id     — phone number ID (numeric string)
  whatsapp_verify_token — webhook verification token you set in Meta dashboard
  whatsapp_webhook_port — local port for webhook server (default: 8080)

Dependencies
------------
    pip install httpx aiohttp
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Optional

try:
    from aiohttp import web
except ImportError:
    raise ImportError("aiohttp required for WhatsApp: pip install aiohttp")

import httpx

from .base import (
    Attachment,
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger = logging.getLogger("ruby.channels.whatsapp")

GRAPH_API = "https://graph.facebook.com/v19.0"


class WhatsAppAdapter(ChannelAdapter):
    """
    WhatsApp Business Cloud API adapter for Ruby.

    Runs an aiohttp webhook server to receive inbound messages and uses
    the Graph API to send replies.
    """

    kind = ChannelKind.WHATSAPP

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._runner: Optional[web.AppRunner] = None
        self._site:   Optional[web.TCPSite]   = None

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        token    = self._vault_get("whatsapp_token")    or self._config.get("token")
        phone_id = self._vault_get("whatsapp_phone_id") or self._config.get("phone_id")
        if not token or not phone_id:
            raise RuntimeError(
                "WhatsApp credentials missing. Store them with:\n"
                "  ruby vault store whatsapp_token <token>\n"
                "  ruby vault store whatsapp_phone_id <phone_number_id>"
            )
        self._token    = token
        self._phone_id = phone_id
        self._verify_token = (
            self._vault_get("whatsapp_verify_token")
            or self._config.get("verify_token", "ruby_webhook")
        )
        port = int(self._config.get("webhook_port", 8080))

        app = web.Application()
        app.router.add_get("/webhook",  self._handle_verify)
        app.router.add_post("/webhook", self._handle_event)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", port)
        await self._site.start()

        self._connected = True
        logger.info("[WhatsApp] Webhook server listening on port %d", port)

    async def disconnect(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._connected = False
        logger.info("[WhatsApp] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        payload = {
            "messaging_product": "whatsapp",
            "to": message.chat_id,
            "type": "text",
            "text": {"body": message.text, "preview_url": False},
        }
        if message.reply_to:
            payload["context"] = {"message_id": message.reply_to}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_API}/{self._phone_id}/messages",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()

    async def send_typing(self, chat_id: str) -> None:
        """WhatsApp supports read receipts but not a persistent typing indicator via Cloud API."""

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    async def _handle_verify(self, request: web.Request) -> web.Response:
        mode      = request.rel_url.query.get("hub.mode")
        token     = request.rel_url.query.get("hub.verify_token")
        challenge = request.rel_url.query.get("hub.challenge")
        if mode == "subscribe" and token == self._verify_token:
            logger.info("[WhatsApp] Webhook verified by Meta.")
            return web.Response(text=challenge)
        return web.Response(status=403, text="Forbidden")

    async def _handle_event(self, request: web.Request) -> web.Response:
        body = await request.read()

        # Validate signature if app secret is available
        app_secret = self._vault_get("whatsapp_app_secret") or self._config.get("app_secret")
        if app_secret:
            sig_header = request.headers.get("X-Hub-Signature-256", "")
            expected   = "sha256=" + hmac.new(
                app_secret.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                logger.warning("[WhatsApp] Signature mismatch — ignoring request.")
                return web.Response(status=403)

        try:
            data = json.loads(body)
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg_data in value.get("messages", []):
                        msg = self._parse_message(msg_data, value)
                        if msg:
                            asyncio.create_task(self._dispatch(msg))
        except Exception as exc:
            logger.exception("[WhatsApp] Error processing webhook: %s", exc)

        return web.Response(text="OK")

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_message(self, msg_data: dict, value: dict) -> Optional[InboundMessage]:
        try:
            msg_type = msg_data.get("type", "text")
            from_num = msg_data.get("from", "")
            msg_id   = msg_data.get("id", "")

            contacts = value.get("contacts", [])
            display  = contacts[0].get("profile", {}).get("name", "") if contacts else ""

            sender = Sender(id=from_num, display_name=display)

            if msg_type == "text":
                text = msg_data.get("text", {}).get("body", "")
                return InboundMessage(
                    channel=ChannelKind.WHATSAPP,
                    chat_id=from_num,
                    message_id=msg_id,
                    sender=sender,
                    text=text,
                    type=MessageType.TEXT,
                    raw=msg_data,
                )
            elif msg_type in ("image", "document", "audio", "video"):
                media_id  = msg_data.get(msg_type, {}).get("id", "")
                mime      = msg_data.get(msg_type, {}).get("mime_type", "")
                filename  = msg_data.get(msg_type, {}).get("filename", media_id)
                caption   = msg_data.get(msg_type, {}).get("caption", "")
                att = Attachment(type=msg_type, url=f"whatsapp://media/{media_id}", mime=mime, filename=filename)
                return InboundMessage(
                    channel=ChannelKind.WHATSAPP,
                    chat_id=from_num,
                    message_id=msg_id,
                    sender=sender,
                    text=caption,
                    type=MessageType.IMAGE if msg_type == "image" else MessageType.FILE,
                    attachments=[att],
                    raw=msg_data,
                )
        except Exception as exc:
            logger.exception("[WhatsApp] Failed to parse message: %s", exc)
        return None
