"""
channels/sms.py
---------------
Ruby – SMS Channel Adapter (Twilio)

Connects Ruby to SMS using the Twilio Messaging API. Inbound SMS messages
arrive via a Twilio webhook (HTTP POST); outbound messages are sent via the
Twilio REST API.

Setup
-----
1. Create a Twilio account at https://www.twilio.com
2. Get a Twilio phone number
3. Store credentials in the vault:
     ruby vault store twilio_account_sid  AC...
     ruby vault store twilio_auth_token   ...
     ruby vault store twilio_from_number  +1234567890
4. Configure your Twilio number's inbound webhook URL (SMS → A Message Comes In):
     POST https://your-host/sms/webhook

Config keys
-----------
  twilio_account_sid   — Twilio Account SID (ACxxxxxxxx)
  twilio_auth_token    — Twilio Auth Token
  twilio_from_number   — Your Twilio phone number in E.164 format (+12125551234)
  sms_webhook_port     — local port for the webhook server (default: 8081)
  sms_webhook_path     — URL path (default: /sms/webhook)

Dependencies
------------
    pip install httpx aiohttp
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import urllib.parse
from typing import Optional

try:
    from aiohttp import web
except ImportError:
    raise ImportError("aiohttp required: pip install aiohttp")

import httpx

from .base import (
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger = logging.getLogger("ruby.channels.sms")

TWILIO_API = "https://api.twilio.com/2010-04-01"
SMS_MAX_LENGTH = 1600   # Twilio segments after 160 chars but we send up to 1600


class SMSAdapter(ChannelAdapter):
    """
    SMS adapter for Ruby using Twilio.

    Hosts a webhook endpoint for inbound SMS and uses Twilio REST API for
    outbound messages.
    """

    kind = ChannelKind.SMS

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._account_sid:  str = ""
        self._auth_token:   str = ""
        self._from_number:  str = ""
        self._runner:       Optional[web.AppRunner] = None

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._account_sid = (
            self._vault_get("twilio_account_sid")
            or self._config.get("account_sid", "")
        )
        self._auth_token = (
            self._vault_get("twilio_auth_token")
            or self._config.get("auth_token", "")
        )
        self._from_number = (
            self._vault_get("twilio_from_number")
            or self._config.get("from_number", "")
        )
        if not self._account_sid or not self._auth_token or not self._from_number:
            raise RuntimeError(
                "Twilio credentials missing. Store them with:\n"
                "  ruby vault store twilio_account_sid  AC...\n"
                "  ruby vault store twilio_auth_token   ...\n"
                "  ruby vault store twilio_from_number  +1234567890"
            )

        port = int(self._config.get("webhook_port", 8081))
        path = self._config.get("webhook_path", "/sms/webhook")

        app = web.Application()
        app.router.add_post(path, self._handle_inbound)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()

        self._connected = True
        logger.info("[SMS] Twilio webhook listening on port %d%s", port, path)

    async def disconnect(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._connected = False
        logger.info("[SMS] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        text = message.text[:SMS_MAX_LENGTH]
        url  = f"{TWILIO_API}/Accounts/{self._account_sid}/Messages.json"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                auth=(self._account_sid, self._auth_token),
                data={
                    "From": self._from_number,
                    "To":   message.chat_id,
                    "Body": text,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug("[SMS] Sent SID=%s to %s", result.get("sid"), message.chat_id)

    # ------------------------------------------------------------------
    # Webhook handler
    # ------------------------------------------------------------------

    async def _handle_inbound(self, request: web.Request) -> web.Response:
        body_bytes = await request.read()

        # Optional: validate Twilio signature
        twilio_sig = request.headers.get("X-Twilio-Signature", "")
        if twilio_sig:
            full_url = str(request.url)
            if not self._validate_signature(full_url, body_bytes, twilio_sig):
                logger.warning("[SMS] Invalid Twilio signature — rejecting request.")
                return web.Response(status=403, text="Forbidden")

        try:
            # Twilio sends application/x-www-form-urlencoded
            params = dict(urllib.parse.parse_qsl(body_bytes.decode("utf-8")))
        except Exception:
            return web.Response(status=400, text="Bad form data")

        msg = self._parse_params(params)
        if msg:
            asyncio.create_task(self._dispatch(msg))

        # Twilio expects TwiML response; empty response == no auto-reply
        return web.Response(
            content_type="text/xml",
            text='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        )

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_params(self, params: dict) -> Optional[InboundMessage]:
        try:
            from_num = params.get("From", "")
            to_num   = params.get("To", "")
            body     = params.get("Body", "")
            msg_sid  = params.get("MessageSid", "")

            # Media attachments (MMS)
            num_media = int(params.get("NumMedia", "0"))
            from .base import Attachment
            attachments = []
            for i in range(num_media):
                url      = params.get(f"MediaUrl{i}", "")
                content  = params.get(f"MediaContentType{i}", "")
                atype    = "image" if content.startswith("image") else "file"
                attachments.append(Attachment(type=atype, url=url, mime=content))

            sender = Sender(id=from_num, display_name=from_num)

            msg_type = (
                MessageType.IMAGE if attachments and attachments[0].type == "image"
                else MessageType.FILE if attachments
                else MessageType.TEXT
            )

            return InboundMessage(
                channel=ChannelKind.SMS,
                chat_id=from_num,
                message_id=msg_sid,
                sender=sender,
                text=body,
                type=msg_type,
                attachments=attachments,
                raw=params,
            )
        except Exception as exc:
            logger.exception("[SMS] Failed to parse inbound params: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Twilio signature validation
    # ------------------------------------------------------------------

    def _validate_signature(self, url: str, body: bytes, signature: str) -> bool:
        """Validate the X-Twilio-Signature header."""
        try:
            params = dict(urllib.parse.parse_qsl(body.decode("utf-8")))
            # Sort params and append sorted key=value pairs to the URL
            sorted_params = "".join(k + v for k, v in sorted(params.items()))
            string_to_sign = url + sorted_params
            mac = hmac.new(
                self._auth_token.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
            expected = base64.b64encode(mac).decode("utf-8")
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False
