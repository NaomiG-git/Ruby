"""Ruby client wrapper for the agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from memu.app.service import MemoryService

from config.settings import Settings

logger = logging.getLogger(__name__)


class MemoryClient:
    """Wrapper for Ruby's MemoryService.
    
    Simplifies the interface for the agent and handles configuration 
    for the specific storage and LLM backend.
    """

    def __init__(self, settings: Settings):
        """Initialize memory client.
        
        Args:
            settings: Application settings
        """
        self._settings = settings
        self._service = self._init_service()
        self._default_user = {"user_id": "default"}  # Default user scope

    def _init_service(self) -> MemoryService:
        """Initialize the Ruby service with configured profiles."""
        logger.info(f"Initializing Ruby service with DB: {self._settings.database_provider}")
        
        return MemoryService(
            llm_profiles=self._settings.get_ruby_llm_profiles(),
            database_config=self._settings.get_ruby_database_config(),
        )

    async def memorize(
        self,
        content: str,
        modality: str = "conversation",
        user_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store content in long-term memory.
        
        This is typically run in the background.
        
        Args:
            content: Text content or file path
            modality: 'conversation', 'document', etc.
            user_id: User identifier for scoping
            extra: Additional metadata
            
        Returns:
            Result dict with extracting items
        """
        user = {"user_id": user_id} if user_id else self._default_user
        
        # Determine if content is a file path or raw text
        # For simplicity in this wrapper, we assume if it looks like a path/URL it is one
        # Otherwise for raw text, memU expects a file or special handling
        # Since memU's memorize() expects a resource_url, for text we might need to save it temp
        # Or check if memU supports direct text ingestion (it prefers files/URLs)
        
        # For direct text (like conversation chunks), we can save to a temp file
        # or implement a custom resource handler.
        # For now, let's assume content is a file path OR we handle text by saving temp.
        
        # IMPORTANT: If content is raw text, we should save it temporarily
        # But for the agent loop, we usually batch conversation to a JSON file
        # Let's assume the agent handles the file creation for now
        
        logger.debug(f"Memorizing content (modality={modality}, user={user})")
        
        try:
            result = await self._service.memorize(
                resource_url=content,
                modality=modality,
                user=user,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to memorize: {e}", exc_info=True)
            raise

    async def recall(
        self,
        query: str | list[dict[str, Any]],
        user_id: str | None = None,
        top_k: int = 5,
        method: str = "rag",  # 'rag' or 'llm'
    ) -> dict[str, Any]:
        """Retrieve relevant memories.
        
        Args:
            query: User query string or message history list
            user_id: User identifier
            top_k: Number of items to retrieve
            method: 'rag' (fast) or 'llm' (deep/proactive)
            
        Returns:
            Dict containing 'items', 'categories', etc.
        """
        user = {"user_id": user_id} if user_id else self._default_user
        
        # Normalize query: memU expects list[dict]
        if isinstance(query, str):
            queries = [{"role": "user", "content": {"text": query}}]
        else:
            # Assuming it's already a list of message dicts
            queries = []
            for q in query:
                content = q.get("content", "")
                if isinstance(content, str):
                    content = {"text": content}
                queries.append({'role': q.get('role', 'user'), 'content': content})

        logger.debug(f"Recalling memory (method={method}, user={user})")
        
        try:
            result = await self._service.retrieve(
                queries=queries,
                where=user,
            )
            
            # The result structure contains 'items', 'categories'
            return result
        except Exception as e:
            logger.error(f"Failed to recall: {e}", exc_info=True)
            # Return empty structure gracefully
            return {"items": [], "categories": []}

    async def get_categories(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Get all memory categories for a user."""
        # For now, we rely on retrieve returning categories, or we could list them
        # MemU's internal structure might be complex, so we'll mock a structure for visualization
        # if the real one isn't easily accessible via the high-level client.
        return []

    async def get_structure(self, user_id: str | None = None) -> dict[str, Any]:
        """Get full memory structure for visualization."""
        # In a real implementation, we'd query the DB for all categories and item counts
        # Here we'll return a sample structure if the DB is empty, or try to fetch some basics
        
        # Try to fetch broad categories
        categories = await self.get_categories(user_id)
        
        # If empty (likely in this PoC), return a sample structure for the UI demo
        if not categories:
            return {
                "name": "Ruby's Memory",
                "children": [
                    {
                        "name": "Preferences",
                        "children": [{"name": "User Habits", "value": 5}, {"name": "Communication Style", "value": 3}]
                    },
                    {
                        "name": "Knowledge",
                        "children": [{"name": "Python Coding", "value": 12}, {"name": "System Ops", "value": 8}]
                    },
                    {
                        "name": "Interactions",
                        "children": [{"name": "Recent Conversations", "value": 15}]
                    }
                ]
            }
        
        return {"name": "Ruby's Memory", "children": categories}

