"""
channels/telegram.py
--------------------
Ruby – Telegram Channel Adapter

Connects Ruby to Telegram using the Bot API (long-polling by default; webhook
optional). Create a bot with @BotFather, store the token in Ruby's vault:

    ruby vault store telegram_bot_token <token>

Config keys
-----------
  telegram_bot_token  — bot token from @BotFather
  telegram_mode       — "polling" (default) | "webhook"
  telegram_webhook_url— HTTPS URL for webhook mode (e.g. https://yourserver/tg)
  telegram_webhook_port — local port for webhook server (default: 8443)

Dependencies
------------
    pip install httpx aiohttp
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

try:
    from aiohttp import web
except ImportError:
    raise ImportError("aiohttp required: pip install aiohttp")

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

logger = logging.getLogger("ruby.channels.telegram")

BOT_API = "https://api.telegram.org/bot{token}"


class TelegramAdapter(ChannelAdapter):
    """
    Telegram Bot API adapter for Ruby.

    Supports long-polling (simplest — no public URL needed) and 
    webhook mode (for production deployments).
    """

    kind = ChannelKind.TELEGRAM

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._token:      str  = ""
        self._base_url:   str  = ""
        self._polling:    bool = True
        self._poll_task:  Optional[asyncio.Task] = None
        self._runner:     Optional[web.AppRunner] = None
        self._offset:     int = 0

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._token = (
            self._vault_get("telegram_bot_token")
            or self._config.get("bot_token", "")
        )
        if not self._token:
            raise RuntimeError(
                "Telegram bot token missing.\n"
                "Create a bot with @BotFather, then:\n"
                "  ruby vault store telegram_bot_token <token>"
            )
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        mode = self._config.get("mode", "polling")

        # Verify token
        me = await self._api("getMe")
        logger.info("[Telegram] Connected as @%s", me.get("username", "?"))

        if mode == "webhook":
            await self._start_webhook()
        else:
            await self._start_polling()

        self._connected = True

    async def disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        if self._runner:
            await self._runner.cleanup()
        self._connected = False
        logger.info("[Telegram] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        payload: dict = {
            "chat_id":    message.chat_id,
            "text":       message.text,
            "parse_mode": "Markdown" if message.parse_mode == "markdown" else "HTML",
        }
        if message.reply_to:
            payload["reply_to_message_id"] = int(message.reply_to)

        await self._api("sendMessage", payload)

    async def send_typing(self, chat_id: str) -> None:
        await self._api("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        # Telegram Bot API v7+ supports setMessageReaction
        await self._api("setMessageReaction", {
            "chat_id":    chat_id,
            "message_id": int(message_id),
            "reaction":   [{"type": "emoji", "emoji": emoji}],
        })

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _start_polling(self) -> None:
        # Delete any existing webhook so getUpdates works
        await self._api("deleteWebhook")
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[Telegram] Long-polling started.")

    async def _poll_loop(self) -> None:
        while True:
            try:
                updates = await self._api("getUpdates", {
                    "offset":  self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "edited_message"],
                })
                for update in updates:
                    self._offset = update["update_id"] + 1
                    msg = self._parse_update(update)
                    if msg:
                        asyncio.create_task(self._dispatch(msg))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("[Telegram] Polling error: %s", exc)
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    async def _start_webhook(self) -> None:
        webhook_url  = self._config.get("webhook_url", "")
        port         = int(self._config.get("webhook_port", 8443))
        secret_token = self._config.get("webhook_secret", "ruby_tg_secret")

        await self._api("setWebhook", {
            "url":          webhook_url,
            "secret_token": secret_token,
        })

        self._webhook_secret = secret_token
        app = web.Application()
        app.router.add_post("/", self._handle_webhook)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()
        logger.info("[Telegram] Webhook server listening on port %d", port)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        # Validate secret token header
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != getattr(self, "_webhook_secret", ""):
            return web.Response(status=403)

        body = await request.json()
        msg = self._parse_update(body)
        if msg:
            asyncio.create_task(self._dispatch(msg))
        return web.Response(text="OK")

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_update(self, update: dict) -> Optional[InboundMessage]:
        try:
            raw_msg = update.get("message") or update.get("edited_message")
            if not raw_msg:
                return None

            chat     = raw_msg.get("chat", {})
            from_    = raw_msg.get("from", {})
            msg_id   = str(raw_msg.get("message_id", ""))
            chat_id  = str(chat.get("id", ""))

            sender = Sender(
                id=str(from_.get("id", "")),
                display_name=f"{from_.get('first_name','')} {from_.get('last_name','')}".strip(),
                username=from_.get("username", ""),
                is_bot=from_.get("is_bot", False),
            )

            # Skip messages from bots
            if sender.is_bot:
                return None

            text = raw_msg.get("text") or raw_msg.get("caption") or ""
            attachments: list[Attachment] = []
            msg_type = MessageType.TEXT

            if "photo" in raw_msg:
                largest = raw_msg["photo"][-1]
                attachments.append(Attachment(type="image", url=f"tg://file/{largest['file_id']}"))
                msg_type = MessageType.IMAGE
            elif "document" in raw_msg:
                doc = raw_msg["document"]
                attachments.append(Attachment(type="file", url=f"tg://file/{doc['file_id']}", filename=doc.get("file_name", "")))
                msg_type = MessageType.FILE
            elif "voice" in raw_msg or "audio" in raw_msg:
                audio = raw_msg.get("voice") or raw_msg.get("audio")
                attachments.append(Attachment(type="audio", url=f"tg://file/{audio['file_id']}"))
                msg_type = MessageType.AUDIO
            elif "video" in raw_msg:
                video = raw_msg["video"]
                attachments.append(Attachment(type="video", url=f"tg://file/{video['file_id']}"))
                msg_type = MessageType.VIDEO

            reply_to = None
            if "reply_to_message" in raw_msg:
                reply_to = str(raw_msg["reply_to_message"].get("message_id", ""))

            return InboundMessage(
                channel=ChannelKind.TELEGRAM,
                chat_id=chat_id,
                message_id=msg_id,
                sender=sender,
                text=text,
                type=msg_type,
                attachments=attachments,
                reply_to=reply_to,
                raw=raw_msg,
            )
        except Exception as exc:
            logger.exception("[Telegram] Failed to parse update: %s", exc)
            return None

    # ------------------------------------------------------------------
    # API helper
    # ------------------------------------------------------------------

    async def _api(self, method: str, params: Optional[dict] = None) -> dict:
        url = f"{self._base_url}/{method}"
        async with httpx.AsyncClient(timeout=35) as client:
            resp = await client.post(url, json=params or {})
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data.get('description')}")
            return data.get("result", {})
