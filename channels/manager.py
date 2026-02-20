"""
channels/manager.py
-------------------
Ruby – Channel Manager

Central hub that owns all channel adapters and wires them to Ruby's model
router. When a message arrives on any channel, the ChannelManager:

  1. Checks the sender is in the peer allowlist (security.identity)
  2. Sends a typing indicator back to the channel
  3. Streams the response from the ModelRouter
  4. Sends the reply back through the same channel

Usage
-----
    import asyncio
    from models.router  import ModelRouter
    from channels.manager import ChannelManager

    router  = ModelRouter()
    router.authenticate_all()

    manager = ChannelManager(router=router)

    # Enable channels selectively:
    manager.add_channel("telegram",  {"mode": "polling"})
    manager.add_channel("discord",   {})
    manager.add_channel("whatsapp",  {"webhook_port": 8080})
    manager.add_channel("slack",     {})
    manager.add_channel("signal",    {})
    manager.add_channel("teams",     {"webhook_port": 3978})
    manager.add_channel("sms",       {})

    asyncio.run(manager.run())
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .base import ChannelAdapter, ChannelKind, InboundMessage, OutboundMessage

logger = logging.getLogger("ruby.channels.manager")

# Registry of channel kind → adapter class (populated on import)
_ADAPTER_REGISTRY: dict[str, type[ChannelAdapter]] = {}


def _load_adapters() -> None:
    """Lazily import adapter classes and register them."""
    global _ADAPTER_REGISTRY
    from .whatsapp import WhatsAppAdapter
    from .telegram import TelegramAdapter
    from .discord  import DiscordAdapter
    from .slack    import SlackAdapter
    from .signal   import SignalAdapter
    from .teams    import TeamsAdapter
    from .sms      import SMSAdapter

    _ADAPTER_REGISTRY = {
        "whatsapp": WhatsAppAdapter,
        "telegram": TelegramAdapter,
        "discord":  DiscordAdapter,
        "slack":    SlackAdapter,
        "signal":   SignalAdapter,
        "teams":    TeamsAdapter,
        "sms":      SMSAdapter,
    }


class ChannelManager:
    """
    Manages all active channel adapters and routes messages to Ruby's brain.

    Parameters
    ----------
    router : ModelRouter
        The model router to send messages to and get responses from.
    vault : Vault | None
        Shared vault instance passed to each adapter.
    identity : IdentityManager | None
        If provided, enforces peer allowlist on inbound messages.
    system_prompt : str | None
        Ruby's system/persona prompt set on the router.
    """

    def __init__(
        self,
        router,
        vault=None,
        identity=None,
        system_prompt: Optional[str] = None,
    ):
        self._router   = router
        self._vault    = vault or self._default_vault()
        self._identity = identity
        self._adapters: list[ChannelAdapter] = []

        if system_prompt:
            self._router.set_system_prompt(system_prompt)

        _load_adapters()

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def add_channel(self, kind: str, config: dict) -> ChannelAdapter:
        """
        Create and register a channel adapter.

        Parameters
        ----------
        kind   : str   — "whatsapp" | "telegram" | "discord" | "slack" |
                         "signal"   | "teams"    | "sms"
        config : dict  — channel-specific config (see each adapter's docstring)

        Returns the adapter instance (not yet connected).
        """
        if kind not in _ADAPTER_REGISTRY:
            raise ValueError(
                f"Unknown channel: {kind!r}. "
                f"Available: {', '.join(_ADAPTER_REGISTRY)}"
            )
        cls     = _ADAPTER_REGISTRY[kind]
        adapter = cls(config=config, vault=self._vault, on_message=self._handle_message)
        self._adapters.append(adapter)
        logger.info("[Manager] Registered channel: %s", kind)
        return adapter

    def add_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a pre-constructed adapter instance."""
        adapter.set_on_message(self._handle_message)
        self._adapters.append(adapter)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect all adapters and run until interrupted."""
        if not self._adapters:
            logger.warning("[Manager] No channels configured — nothing to do.")
            return

        logger.info("[Manager] Connecting %d channel(s)...", len(self._adapters))
        connect_tasks = [a.connect() for a in self._adapters]
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

        for adapter, result in zip(self._adapters, results):
            if isinstance(result, Exception):
                logger.error(
                    "[Manager] Failed to connect %s: %s",
                    adapter.kind.value, result
                )

        connected = [a for a in self._adapters if a.is_connected]
        logger.info("[Manager] %d/%d channel(s) connected. Ruby is live.", len(connected), len(self._adapters))

        try:
            await asyncio.Event().wait()  # run forever
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully disconnect all adapters."""
        logger.info("[Manager] Shutting down channels...")
        tasks = [a.disconnect() for a in self._adapters if a.is_connected]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[Manager] All channels disconnected.")

    # ------------------------------------------------------------------
    # Message handler — the core routing logic
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: InboundMessage) -> None:
        """
        Called for every inbound message from any channel.

        Flow:
          1. Allowlist check (if IdentityManager is configured)
          2. Log inbound
          3. Typing indicator
          4. Route to ModelRouter (streaming)
          5. Send reply
        """
        # 1. Allowlist check
        if self._identity:
            peer_id = f"{msg.channel.value}:{msg.sender.id}"
            if not self._identity.is_peer_allowed(peer_id):
                logger.warning(
                    "[Manager] Rejected message from unlisted peer: %s", peer_id
                )
                return

        # 2. Log
        logger.info(
            "[Manager] [%s] %s → %r",
            msg.channel.value,
            msg.sender.display_name or msg.sender.id,
            msg.text[:80] + ("..." if len(msg.text) > 80 else ""),
        )

        # 3. Typing indicator (fire-and-forget)
        adapter = self._adapter_for(msg.channel)
        if adapter:
            asyncio.create_task(_safe(adapter.send_typing(msg.chat_id)))

        # 4. Build user content (text + attachment descriptions)
        user_text = self._build_user_text(msg)

        # 5. Stream response and collect full reply
        full_reply = ""
        try:
            gen = self._router.stream(user_text, use_history=True)
            # Collect stream — for most channels we send the complete response
            # (for future: could send chunks for platforms that support edit-message)
            for chunk in gen:
                full_reply += chunk
        except Exception as exc:
            logger.exception("[Manager] Router error: %s", exc)
            full_reply = "Sorry, I ran into an error. Please try again."

        if not full_reply.strip():
            return

        # 6. Send reply
        if adapter:
            out = OutboundMessage(
                chat_id=msg.chat_id,
                text=full_reply,
                reply_to=msg.message_id,
            )
            try:
                await adapter.send(out)
            except Exception as exc:
                logger.exception(
                    "[Manager] Failed to send reply on %s: %s",
                    msg.channel.value, exc
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapter_for(self, kind: ChannelKind) -> Optional[ChannelAdapter]:
        for a in self._adapters:
            if a.kind == kind and a.is_connected:
                return a
        return None

    @staticmethod
    def _build_user_text(msg: InboundMessage) -> str:
        """Compose a text representation of the inbound message for the router."""
        parts = []
        if msg.text:
            parts.append(msg.text)
        for att in msg.attachments:
            parts.append(f"[{att.type.upper()} attachment: {att.filename or att.url}]")
        return "\n".join(parts) or "(empty message)"

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

async def _safe(coro) -> None:
    """Await a coroutine and swallow exceptions (for fire-and-forget tasks)."""
    try:
        await coro
    except Exception:
        pass
