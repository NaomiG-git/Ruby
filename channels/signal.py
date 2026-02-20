"""
channels/signal.py
------------------
Ruby – Signal Channel Adapter

Connects Ruby to Signal via signal-cli (https://github.com/AsamK/signal-cli)
running in JSON-RPC daemon mode. signal-cli handles the Signal protocol
(libsignal), exposing a local JSON-RPC socket that Ruby communicates with.

Setup
-----
1. Install signal-cli (Java required):
     https://github.com/AsamK/signal-cli/releases
2. Register or link a phone number:
     signal-cli -a +1234567890 register
     signal-cli -a +1234567890 verify <code>
3. Start signal-cli in daemon mode:
     signal-cli -a +1234567890 daemon --socket /tmp/signal.sock
4. Store your number in the vault:
     ruby vault store signal_account +1234567890
     ruby vault store signal_socket  /tmp/signal.sock   (optional override)

Config keys
-----------
  signal_account  — your registered Signal phone number (+E.164 format)
  signal_socket   — path to JSON-RPC Unix socket (default: /tmp/signal.sock)

Dependencies
------------
    Requires signal-cli to be running externally.
    pip install aiofiles  (optional, for async file I/O)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from .base import (
    Attachment,
    ChannelAdapter,
    ChannelKind,
    InboundMessage,
    MessageType,
    OutboundMessage,
    Sender,
)

logger   = logging.getLogger("ruby.channels.signal")
SOCKET   = "/tmp/signal.sock"
TIMEOUT  = 30


class SignalAdapter(ChannelAdapter):
    """
    Signal adapter for Ruby via signal-cli JSON-RPC daemon.

    Messages arrive as newline-delimited JSON on the daemon socket.
    """

    kind = ChannelKind.SIGNAL

    def __init__(self, config: dict, vault=None, on_message=None):
        super().__init__(config, vault, on_message)
        self._account:    str = ""
        self._socket:     str = SOCKET
        self._reader:     Optional[asyncio.StreamReader]  = None
        self._writer:     Optional[asyncio.StreamWriter]  = None
        self._recv_task:  Optional[asyncio.Task]          = None
        self._rpc_id:     int = 0

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._account = (
            self._vault_get("signal_account")
            or self._config.get("account", "")
        )
        self._socket = (
            self._vault_get("signal_socket")
            or self._config.get("socket", SOCKET)
        )
        if not self._account:
            raise RuntimeError(
                "Signal account number missing.\n"
                "  ruby vault store signal_account +1234567890"
            )

        self._reader, self._writer = await asyncio.open_unix_connection(self._socket)
        # Subscribe to incoming messages
        await self._rpc("subscribeReceive", {"account": self._account})

        self._recv_task = asyncio.create_task(self._receive_loop())
        self._connected = True
        logger.info("[Signal] Connected — account %s", self._account)

    async def disconnect(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._connected = False
        logger.info("[Signal] Disconnected.")

    async def send(self, message: OutboundMessage) -> None:
        params: dict = {
            "account":     self._account,
            "recipient":   [message.chat_id],
            "message":     message.text,
        }
        await self._rpc("send", params)

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        while True:
            try:
                line = await asyncio.wait_for(self._reader.readline(), timeout=None)
                if not line:
                    logger.warning("[Signal] Socket closed by daemon.")
                    break
                data = json.loads(line.decode("utf-8").strip())
                msg = self._parse_message(data)
                if msg:
                    asyncio.create_task(self._dispatch(msg))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("[Signal] Receive error: %s", exc)
                await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_message(self, data: dict) -> Optional[InboundMessage]:
        try:
            # signal-cli JSON-RPC notification format
            method = data.get("method", "")
            if method != "receive":
                return None

            params   = data.get("params", {})
            envelope = params.get("envelope", {})
            data_msg = envelope.get("dataMessage", {})

            if not data_msg:
                return None  # typing notifications, receipts, etc.

            source       = envelope.get("source", "")
            source_name  = envelope.get("sourceName", source)
            msg_timestamp= str(envelope.get("timestamp", ""))
            text         = data_msg.get("message", "") or ""

            sender = Sender(id=source, display_name=source_name)

            attachments: list[Attachment] = []
            for att in data_msg.get("attachments", []):
                atype = att.get("contentType", "application/octet-stream")
                attachments.append(Attachment(
                    type="image" if atype.startswith("image") else "file",
                    filename=att.get("filename", ""),
                    mime=atype,
                ))

            msg_type = (
                MessageType.IMAGE if attachments and attachments[0].type == "image"
                else MessageType.FILE if attachments
                else MessageType.TEXT
            )

            # Determine chat_id: group or 1:1
            group_info = data_msg.get("groupInfo", {})
            chat_id    = group_info.get("groupId", source) if group_info else source

            return InboundMessage(
                channel=ChannelKind.SIGNAL,
                chat_id=chat_id,
                message_id=msg_timestamp,
                sender=sender,
                text=text,
                type=msg_type,
                attachments=attachments,
                raw=data,
            )
        except Exception as exc:
            logger.exception("[Signal] Failed to parse message: %s", exc)
            return None

    # ------------------------------------------------------------------
    # JSON-RPC helper
    # ------------------------------------------------------------------

    async def _rpc(self, method: str, params: dict) -> dict:
        self._rpc_id += 1
        request = json.dumps({
            "jsonrpc": "2.0",
            "id":      self._rpc_id,
            "method":  method,
            "params":  params,
        })
        self._writer.write((request + "\n").encode("utf-8"))
        await self._writer.drain()
        # Read response
        try:
            response_line = await asyncio.wait_for(self._reader.readline(), timeout=TIMEOUT)
            return json.loads(response_line.decode("utf-8"))
        except asyncio.TimeoutError:
            logger.warning("[Signal] RPC timeout for method: %s", method)
            return {}
