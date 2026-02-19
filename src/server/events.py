
import asyncio
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class EventManager:
    """Manages subscribers for Server-Sent Events (SSE)."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncGenerator[asyncio.Queue, None]:
        """Subscribe to events."""
        queue = asyncio.Queue()
        self._queues.add(queue)
        logger.debug(f"Client subscribed. Total subscribers: {len(self._queues)}")
        try:
            yield queue
        finally:
            self._queues.remove(queue)
            logger.debug(f"Client unsubscribed. Total subscribers: {len(self._queues)}")

    async def broadcast(self, event_type: str, data: dict | str) -> None:
        """Broadcast an event to all subscribers."""
        if not self._queues:
            return

        message = {
            "type": event_type,
            "content": data
        }
        
        # Dead simple serialization for now
        import json
        payload = json.dumps(message)

        for queue in self._queues:
            await queue.put(payload)
