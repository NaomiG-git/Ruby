"""Anthropic (Claude) LLM provider implementation."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Any

from src.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider implementation.
    
    Supports Claude 3.5 Sonnet, Claude 3 Opus, and other Anthropic models.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        **kwargs: Any,
    ):
        """Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key
            model: Default chat model
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "anthropic package required. Install with: pip install anthropic"
            )
        
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"

    @property
    def current_model(self) -> str:
        return self._model

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic format.
        
        Anthropic requires:
        1. System message passed separately.
        2. Strict alternating user/assistant roles.
        3. No trailing whitespace in assistant messages.
        
        Returns:
            Tuple of (system_prompt, messages)
        """
        system_prompt = None
        raw_converted: list[dict[str, Any]] = []
        
        # Phase 1: Basic conversion and categorization
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            
            if role == "system":
                system_prompt = content
                continue
            
            if role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if not tool_call_id:
                    logger.warning(f"Tool message missing tool_call_id: {msg}")
                    continue
                    
                raw_converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": str(content)
                    }]
                })
            elif role == "assistant":
                blocks = []
                if content:
                    # Strip trailing whitespace as required by Anthropic
                    blocks.append({"type": "text", "text": str(content).rstrip()})
                
                if "tool_calls" in msg:
                    for call in msg["tool_calls"]:
                        func = call.get("function", {})
                        try:
                            args = func.get("arguments", "{}")
                            import json
                            if isinstance(args, str):
                                args = json.loads(args)
                        except:
                            args = {}
                            
                        blocks.append({
                            "type": "tool_use",
                            "id": call.get("id"),
                            "name": func.get("name"),
                            "input": args
                        })
                
                if blocks:
                    raw_converted.append({
                        "role": "assistant",
                        "content": blocks
                    })
            else:
                # User messages
                if content:
                    raw_converted.append({
                        "role": "user",
                        "content": str(content)
                    })

        # Phase 2: Merge consecutive roles
        if not raw_converted:
            return system_prompt, []
            
        final_converted: list[dict[str, Any]] = []
        for msg in raw_converted:
            if not final_converted or final_converted[-1]["role"] != msg["role"]:
                final_converted.append(msg)
            else:
                # Merge content
                prev = final_converted[-1]
                prev_content = prev["content"]
                curr_content = msg["content"]
                
                # Normalize both to lists for easier merging
                if not isinstance(prev_content, list):
                    prev_content = [{"type": "text", "text": prev_content}]
                if not isinstance(curr_content, list):
                    curr_content = [{"type": "text", "text": curr_content}]
                
                # Combine lists
                prev["content"] = prev_content + curr_content
                
        return system_prompt, final_converted

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to Anthropic."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)
        system_prompt, converted_messages = self._convert_messages(validated_messages)

        request_params: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_tokens": max_tokens or 4096,
        }
        
        if system_prompt:
            request_params["system"] = system_prompt
        
        if temperature is not None:
            request_params["temperature"] = min(temperature, 1.0)
            
        if tools:
            # Convert internal Tool objects to Anthropic format
            anthropic_tools = []
            for tool in tools:
                anthropic_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters
                })
            request_params["tools"] = anthropic_tools

        logger.debug(f"Anthropic chat request: model={model}, messages={len(messages)}, tools={len(tools) if tools else 0}")

        response = await self._client.messages.create(**request_params)
        
        content = ""
        tool_calls = []
        
        # Parse response content blocks
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                import json
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input) # OpenAI expects string encoded JSON
                    }
                })

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            finish_reason=response.stop_reason or "stop",
            raw_response=response,
            tool_calls=tool_calls if tool_calls else None
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response from Anthropic."""
        model = model or self._model
        validated_messages = self.validate_messages(messages)
        system_prompt, converted_messages = self._convert_messages(validated_messages)

        request_params: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        
        if system_prompt:
            request_params["system"] = system_prompt
        if temperature is not None:
            request_params["temperature"] = min(temperature, 1.0)

        async with self._client.messages.stream(**request_params) as stream:
            async for text in stream.text_stream:
                yield text

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings.
        
        Note: Anthropic doesn't have native embedding API.
        This raises NotImplementedError - use OpenAI embeddings instead.
        """
        raise NotImplementedError(
            "Anthropic does not provide embedding API. "
            "Use OpenAI or another provider for embeddings."
        )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token count for Anthropic models.
        
        Uses a simple heuristic since Anthropic doesn't provide tokenizer.
        For accurate counts, use the API response.
        """
        # Rough estimate: ~4 chars per token for English
        return len(text) // 4
