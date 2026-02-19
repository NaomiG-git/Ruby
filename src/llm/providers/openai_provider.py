"""OpenAI LLM provider implementation."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Any

import tiktoken
from openai import AsyncOpenAI

from src.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI API provider implementation.
    
    Supports GPT-4o, GPT-4o-mini, o1, and other OpenAI models.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-small",
        **kwargs: Any,
    ):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Default chat model
            embedding_model: Default embedding model
        """
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._embedding_model = embedding_model
        self._tokenizers: dict[str, tiktoken.Encoding] = {}

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    @property
    def current_model(self) -> str:
        return self._model

    def _get_tokenizer(self, model: str) -> tiktoken.Encoding:
        """Get or create tokenizer for model."""
        if model not in self._tokenizers:
            try:
                self._tokenizers[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to cl100k_base for unknown models
                self._tokenizers[model] = tiktoken.get_encoding("cl100k_base")
        return self._tokenizers[model]

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to OpenAI."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)

        # Build request parameters
        request_params: dict[str, Any] = {
            "model": model,
            "messages": validated_messages,
            "temperature": temperature,
        }
        if max_tokens:
            request_params["max_tokens"] = max_tokens

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
            request_params["tools"] = formatted_tools

        # Add any extra kwargs
        request_params.update(kwargs)

        logger.debug(f"OpenAI chat request: model={model}, messages={len(messages)}, tools={len(tools) if tools else 0}")

        response = await self._client.chat.completions.create(**request_params)
        
        message = response.choices[0].message
        
        # Extract tool calls if present
        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                    "type": tc.type,
                })

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=response.choices[0].finish_reason or "stop",
            raw_response=response,
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response from OpenAI."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)

        stream = await self._client.chat.completions.create(
            model=model,
            messages=validated_messages,
            temperature=temperature,
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings using OpenAI."""
        model = model or self._embedding_model
        
        # Normalize to list
        texts = [text] if isinstance(text, str) else text

        response = await self._client.embeddings.create(
            model=model,
            input=texts,
        )

        return [item.embedding for item in response.data]

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Count tokens using tiktoken."""
        model = model or self._model
        tokenizer = self._get_tokenizer(model)
        return len(tokenizer.encode(text))
