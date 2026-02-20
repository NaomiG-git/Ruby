"""
scheduling/webhooks.py
----------------------
Ruby – Webhook Trigger System

Inbound webhooks  — external services (GitHub, Stripe, Zapier, IFTTT, etc.)
                    POST to Ruby's webhook endpoint and trigger a prompt/chain.

Outbound webhooks — Ruby calls external URLs when certain events fire
                    (e.g. after a cron job runs, when a reminder fires, etc.)

Inbound webhook URL pattern:
    POST http://your-host:<port>/webhook/<name>

Each registered webhook has:
  - A unique name and optional HMAC secret for signature validation
  - A prompt template (Jinja-style {{key}} substitution from payload)
  - An optional target channel/chat to deliver the response to

Usage
-----
    from scheduling.webhooks import WebhookServer

    server = WebhookServer(router=router, channel_mgr=mgr)

    # Register an inbound webhook
    server.register_inbound(
        name="github_push",
        prompt="A GitHub push just happened to {{repository.name}} branch {{ref}}. Summarise the changes: {{commits}}",
        channel="telegram",
        chat_id="+1234567890",
        secret="my_webhook_secret",   # optional HMAC-SHA256 validation
    )

    # Register an outbound webhook (called by Ruby on demand)
    server.register_outbound(
        name="notify_slack",
        url="https://hooks.slack.com/services/xxx/yyy/zzz",
        method="POST",
        headers={"Content-Type": "application/json"},
        body_template='{\"text\": \"{{message}}\"}',
    )
    await server.call_outbound("notify_slack", {"message": "Ruby says hi!"})

    await server.run()   # starts the HTTP listener
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

try:
    from aiohttp import web
except ImportError:
    raise ImportError("aiohttp required: pip install aiohttp")

import httpx

logger = logging.getLogger("ruby.scheduling.webhooks")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InboundWebhook:
    name:       str
    prompt:     str            # template: {{key.subkey}} substituted from payload
    channel:    str  = ""
    chat_id:    str  = ""
    secret:     str  = ""      # HMAC-SHA256 signing secret (optional)
    enabled:    bool = True
    hit_count:  int  = 0
    last_hit:   float = 0.0


@dataclass
class OutboundWebhook:
    name:          str
    url:           str
    method:        str  = "POST"
    headers:       dict = field(default_factory=dict)
    body_template: str  = ""   # template; leave empty for JSON pass-through
    enabled:       bool = True
    timeout:       int  = 30


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{([\w.]+)\}\}")

def _render(template: str, context: dict) -> str:
    """Simple {{key}} and {{nested.key}} substitution from a flat/nested dict."""
    def replace(m: re.Match) -> str:
        path  = m.group(1).split(".")
        value = context
        for part in path:
            if isinstance(value, dict):
                value = value.get(part, "")
            else:
                value = ""
                break
        return str(value)
    return _TEMPLATE_RE.sub(replace, template)


# ---------------------------------------------------------------------------
# WebhookServer
# ---------------------------------------------------------------------------

class WebhookServer:
    """
    Inbound + outbound webhook manager for Ruby.

    Parameters
    ----------
    router      : ModelRouter
    channel_mgr : ChannelManager | None
    vault       : Vault | None
    port        : int    — local port for the inbound HTTP server (default: 8888)
    host        : str    — bind address (default: 0.0.0.0)
    base_path   : str    — URL prefix (default: /webhook)
    """

    STORE_KEY_IN  = "webhooks_inbound"
    STORE_KEY_OUT = "webhooks_outbound"

    def __init__(
        self,
        router,
        channel_mgr=None,
        vault=None,
        port: int = 8888,
        host: str = "0.0.0.0",
        base_path: str = "/webhook",
    ):
        self._router      = router
        self._channel_mgr = channel_mgr
        self._vault       = vault or self._default_vault()
        self._port        = port
        self._host        = host
        self._base_path   = base_path.rstrip("/")
        self._inbound:    dict[str, InboundWebhook]  = {}
        self._outbound:   dict[str, OutboundWebhook] = {}
        self._runner:     Optional[web.AppRunner]    = None
        self._load()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_inbound(
        self,
        name:    str,
        prompt:  str,
        channel: str = "",
        chat_id: str = "",
        secret:  str = "",
        enabled: bool = True,
    ) -> InboundWebhook:
        wh = InboundWebhook(
            name=name, prompt=prompt,
            channel=channel, chat_id=chat_id,
            secret=secret, enabled=enabled,
        )
        self._inbound[name] = wh
        self._save()
        logger.info("[Webhooks] Inbound registered: %s  → %s%s/%s", name, self._host, self._base_path, name)
        return wh

    def register_outbound(
        self,
        name:          str,
        url:           str,
        method:        str  = "POST",
        headers:       Optional[dict] = None,
        body_template: str  = "",
        enabled:       bool = True,
        timeout:       int  = 30,
    ) -> OutboundWebhook:
        wh = OutboundWebhook(
            name=name, url=url, method=method,
            headers=headers or {}, body_template=body_template,
            enabled=enabled, timeout=timeout,
        )
        self._outbound[name] = wh
        self._save()
        logger.info("[Webhooks] Outbound registered: %s → %s", name, url)
        return wh

    def remove_inbound(self, name: str) -> None:
        del self._inbound[name]
        self._save()

    def remove_outbound(self, name: str) -> None:
        del self._outbound[name]
        self._save()

    # ------------------------------------------------------------------
    # Outbound calling
    # ------------------------------------------------------------------

    async def call_outbound(self, name: str, context: dict) -> dict:
        """
        Fire an outbound webhook by name, substituting *context* into the
        body template. Returns the response JSON (or empty dict on error).
        """
        wh = self._outbound.get(name)
        if not wh:
            raise KeyError(f"No outbound webhook named: {name!r}")
        if not wh.enabled:
            logger.info("[Webhooks] Outbound %s is disabled — skipping.", name)
            return {}

        if wh.body_template:
            body_str = _render(wh.body_template, context)
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                body = {"text": body_str}
        else:
            body = context

        async with httpx.AsyncClient(timeout=wh.timeout) as client:
            method = getattr(client, wh.method.lower(), client.post)
            resp   = await method(wh.url, headers=wh.headers, json=body)
            resp.raise_for_status()
            logger.info("[Webhooks] Outbound %s → %d", name, resp.status_code)
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}

    # ------------------------------------------------------------------
    # HTTP server
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the inbound webhook HTTP listener."""
        app = web.Application()
        app.router.add_post(f"{self._base_path}/{{name}}", self._handle_inbound)
        app.router.add_get(f"{self._base_path}/{{name}}", self._handle_ping)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("[Webhooks] Inbound server listening on %s:%d%s/<name>", self._host, self._port, self._base_path)

        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------

    async def _handle_ping(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        if name in self._inbound:
            return web.json_response({"status": "ok", "webhook": name})
        return web.Response(status=404, text="Not found")

    async def _handle_inbound(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        wh   = self._inbound.get(name)

        if not wh:
            return web.Response(status=404, text=f"No webhook registered: {name!r}")
        if not wh.enabled:
            return web.Response(status=503, text="Webhook disabled")

        body = await request.read()

        # Validate HMAC signature if a secret is set
        if wh.secret:
            sig = request.headers.get("X-Hub-Signature-256", "") or \
                  request.headers.get("X-Signature-256", "")
            expected = "sha256=" + hmac.new(wh.secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                logger.warning("[Webhooks] Signature mismatch for webhook: %s", name)
                return web.Response(status=403, text="Invalid signature")

        # Parse payload
        try:
            content_type = request.content_type or ""
            if "json" in content_type:
                payload = json.loads(body)
            elif "form" in content_type:
                from urllib.parse import parse_qs
                payload = {k: v[0] if len(v) == 1 else v
                           for k, v in parse_qs(body.decode()).items()}
            else:
                payload = {"raw": body.decode("utf-8", errors="replace")}
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}

        # Render prompt template with payload data
        prompt = _render(wh.prompt, payload)

        # Update stats
        wh.hit_count += 1
        wh.last_hit   = time.time()
        self._save()

        # Fire and forget — process the trigger asynchronously
        asyncio.create_task(self._process_trigger(wh, prompt, payload))

        return web.json_response({"status": "accepted", "webhook": name})

    async def _process_trigger(self, wh: InboundWebhook, prompt: str, payload: dict) -> None:
        logger.info("[Webhooks] Trigger fired: %s", wh.name)
        try:
            response = ""
            gen = self._router.stream(prompt, use_history=False)
            for chunk in gen:
                response += chunk
        except Exception as exc:
            logger.exception("[Webhooks] Router error: %s", exc)
            response = f"[Webhook trigger error: {exc}]"

        if wh.channel and wh.chat_id and self._channel_mgr:
            from channels.base import OutboundMessage, ChannelKind
            try:
                adapter = self._channel_mgr._adapter_for(ChannelKind(wh.channel))
                if adapter:
                    out = OutboundMessage(chat_id=wh.chat_id, text=response)
                    await adapter.send(out)
            except Exception as exc:
                logger.exception("[Webhooks] Delivery error: %s", exc)
        else:
            logger.info("[Webhooks] Trigger response:\n%s", response[:300])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            self._vault.store(self.STORE_KEY_IN,  json.dumps({k: asdict(v) for k, v in self._inbound.items()}))
            self._vault.store(self.STORE_KEY_OUT, json.dumps({k: asdict(v) for k, v in self._outbound.items()}))
        except Exception as exc:
            logger.warning("[Webhooks] Save error: %s", exc)

    def _load(self) -> None:
        try:
            raw = self._vault.retrieve(self.STORE_KEY_IN)
            for k, d in json.loads(raw).items():
                self._inbound[k] = InboundWebhook(**d)
        except KeyError:
            pass
        try:
            raw = self._vault.retrieve(self.STORE_KEY_OUT)
            for k, d in json.loads(raw).items():
                self._outbound[k] = OutboundWebhook(**d)
        except KeyError:
            pass

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()
