"""Ollama local LLM provider implementation."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Any

import httpx

from src.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama local model provider implementation.
    
    Supports any model available through Ollama (llama3.2, codellama, mistral, etc.)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        **kwargs: Any,
    ):
        """Initialize Ollama provider.
        
        Args:
            base_url: Ollama server URL
            model: Default model name
        """
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return "llama3.2"

    @property
    def current_model(self) -> str:
        return self._model

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Extract system prompt and convert messages for Ollama."""
        system_prompt = None
        converted = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                msg_copy = {
                    "role": msg["role"],
                    "content": msg.get("content"),
                }
                # Support tool calls in history
                if msg.get("tool_calls"):
                    msg_copy["tool_calls"] = msg["tool_calls"]
                if msg.get("tool_call_id"):
                    msg_copy["tool_call_id"] = msg["tool_call_id"]
                if msg.get("name"):
                    msg_copy["name"] = msg["name"]
                    
                converted.append(msg_copy)
        
        return system_prompt, converted

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to Ollama."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)
        system_prompt, converted_messages = self._convert_messages(validated_messages)

        request_body: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        if system_prompt:
            request_body["system"] = system_prompt
        if max_tokens:
            request_body["options"]["num_predict"] = max_tokens

        # Add tools if provided
        if tools:
            formatted_tools = []
            for tool in tools:
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                })
            request_body["tools"] = formatted_tools

        logger.debug(f"Ollama chat request: model={model}, messages={len(messages)}, tools={len(tools) if tools else 0}")

        response = await self._client.post("/api/chat", json=request_body)
        response.raise_for_status()
        data = response.json()
        
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls")

        return LLMResponse(
            content=content,
            model=data.get("model", model),
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
            finish_reason=data.get("done_reason", "stop"),
            raw_response=data,
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response from Ollama."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)
        system_prompt, converted_messages = self._convert_messages(validated_messages)

        request_body: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
            },
        }
        
        if system_prompt:
            request_body["system"] = system_prompt

        async with self._client.stream("POST", "/api/chat", json=request_body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings using Ollama."""
        model = model or "nomic-embed-text"
        
        texts = [text] if isinstance(text, str) else text
        embeddings = []
        
        for t in texts:
            response = await self._client.post(
                "/api/embeddings",
                json={"model": model, "prompt": t},
            )
            response.raise_for_status()
            data = response.json()
            embeddings.append(data.get("embedding", []))
        
        return embeddings

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token count for Ollama models.
        
        Uses a simple heuristic since token counting varies by model.
        """
        # Rough estimate: ~4 chars per token
        return len(text) // 4

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
