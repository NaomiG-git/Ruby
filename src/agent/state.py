"""Conversation state management."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """Manages the state of a single conversation session."""

    session_id: str
    user_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    persistence_path: str | None = None

    def __post_init__(self):
        """Load history if path provided."""
        if self.persistence_path:
            self.load()

    def add_message(self, role: str, content: str | list | dict, tool_calls: list | None = None, tool_call_id: str | None = None) -> None:
        """Add a message to history."""
        msg = {"role": role, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
            
        self.history.append(msg)
        self.updated_at = datetime.now()
        self.save()

    def get_context_window(self, max_messages: int = 20) -> list[dict[str, str]]:
        """Get the most recent messages for context."""
        return self.history[-max_messages:]

    def clear(self) -> None:
        """Clear conversation history."""
        self.history = []
        self.updated_at = datetime.now()
        self.save()
        logger.info(f"Cleared history for session {self.session_id}")

    def to_chat_format(self) -> list[dict[str, str]]:
        """Export in standard chat format."""
        return self.history

    def save(self) -> None:
        """Persist history to disk."""
        if not self.persistence_path:
            return
        try:
            import json
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump({
                    "history": self.history,
                    "metadata": self.metadata,
                    "session_id": self.session_id,
                    "updated_at": self.updated_at.isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def load(self) -> None:
        """Load history from disk."""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return
        try:
            import json
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.history = data.get("history", [])
                self.metadata = data.get("metadata", {})
                # We keep the current session_id unless we want to resume exactly
                if "updated_at" in data:
                    self.updated_at = datetime.fromisoformat(data["updated_at"])
            logger.info(f"Loaded {len(self.history)} messages from persistent storage.")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
