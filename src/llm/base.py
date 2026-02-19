"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Any


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str
    model: str
    usage: dict = field(default_factory=dict)
    finish_reason: str = "stop"
    raw_response: Any = None
    tool_calls: list[dict] | None = None

    @property
    def input_tokens(self) -> int:
        """Get input token count."""
        return self.usage.get("input_tokens", self.usage.get("prompt_tokens", 0))

    @property
    def output_tokens(self) -> int:
        """Get output token count."""
        return self.usage.get("output_tokens", self.usage.get("completion_tokens", 0))

    @property
    def total_tokens(self) -> int:
        """Get total token count."""
        return self.usage.get("total_tokens", self.input_tokens + self.output_tokens)


class LLMProvider(ABC):
    """Abstract base class for LLM providers.
    
    All provider implementations must inherit from this class and implement
    the required methods. This ensures consistent interfaces across providers.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'anthropic', 'google')."""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        pass

    @property
    def current_model(self) -> str:
        """Currently configured model."""
        return getattr(self, "_model", self.default_model)

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            model: Model to use (defaults to provider's default)
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: List of tools available to the model
            **kwargs: Provider-specific arguments
            
        Returns:
            LLMResponse with the generated content
        """
        pass

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response.
        
        Args:
            messages: List of message dicts
            model: Model to use
            temperature: Sampling temperature
            **kwargs: Provider-specific arguments
            
        Yields:
            String chunks of the response
        """
        pass

    @abstractmethod
    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for text.
        
        Args:
            text: Single string or list of strings to embed
            model: Embedding model to use
            
        Returns:
            List of embedding vectors (one per input text)
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Count tokens in text for the given model.
        
        Args:
            text: Text to count tokens for
            model: Model to use for tokenization
            
        Returns:
            Token count
        """
        pass

    def validate_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate and normalize message format.
        
        Args:
            messages: List of message dicts
            
        Returns:
            Validated and normalized messages
        """
        validated = []
        for msg in messages:
            if "role" not in msg:
                raise ValueError(f"Message must have 'role': {msg}")
            
            new_msg = {
                "role": msg["role"],
                "content": msg.get("content"), # Content can be None for assistant tool calls
            }
            
            # Pass through optional fields needed for tools
            if "tool_calls" in msg:
                new_msg["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                new_msg["tool_call_id"] = msg["tool_call_id"]
            if "name" in msg:
                new_msg["name"] = msg["name"]
                
            validated.append(new_msg)
        return validated
