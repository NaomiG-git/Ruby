"""Google Gemini LLM provider implementation."""

from __future__ import annotations

import os
import json
import logging
from typing import AsyncIterator, Any

from src.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class GoogleProvider(LLMProvider):
    """Google Gemini API provider implementation.
    
    Supports Gemini Pro, Gemini 1.5 Pro, and other Google AI models.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        **kwargs: Any,
    ):
        """Initialize Google provider.
        
        Args:
            api_key: Google AI API key
            model: Default chat model
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package required. Install with: pip install google-generativeai"
            )
        
        if not model.startswith("models/"):
            model = f"models/{model}"
        
        genai.configure(api_key=api_key)
        self._genai = genai
        self._model = model
        self._client = genai.GenerativeModel(model)

    @property
    def name(self) -> str:
        return "google"

    @property
    def default_model(self) -> str:
        return "gemini-2.0-flash"

    @property
    def current_model(self) -> str:
        return self._model

    def _convert_tool_to_gemini(self, tool: Any) -> dict[str, Any]:
        """Convert a standard Tool/FunctionTool to Gemini format."""
        if hasattr(tool, "parameters"):
            schema = tool.parameters
        else:
            return None

        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema
        }

    def _convert_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Gemini format (handling tools)."""
        system_instruction = None
        history = []
        
        # Helper to find tool name by ID from previous messages
        def find_tool_name(call_id: str) -> str:
            for m in reversed(messages):
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        if tc["id"] == call_id:
                            return tc["function"]["name"]
            return "unknown_tool"

        pending_role = None
        pending_parts = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")
            
            if role == "system":
                if system_instruction:
                    system_instruction += "\n\n" + content
                else:
                    system_instruction = content
                continue

            # Gemini High-level roles: 'user', 'model'
            # Low-level turns can include 'function'
            # For start_chat(history=...), roles must be 'user' or 'model'
            current_role = "user" if role in ["user", "tool"] else "model"

            # 1. Gather parts for this message
            parts = []
            
            # Handle Text / Images
            if isinstance(content, list):
                for p in content:
                    if isinstance(p, str):
                        # Handle plain strings in a list (check for local files)
                        path = p.strip()
                        ext = path.lower().split('.')[-1]
                        if ext in ('png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'avi', 'webm', 'mkv') and os.path.exists(path):
                            import mimetypes, base64
                            mime_type, _ = mimetypes.guess_type(path)
                            if not mime_type:
                                if ext == 'mp4': mime_type = 'video/mp4'
                                elif ext == 'mov': mime_type = 'video/quicktime'
                                elif ext == 'webm': mime_type = 'video/webm'
                            try:
                                with open(path, "rb") as f:
                                    encoded = base64.b64encode(f.read()).decode("utf-8")
                                    parts.append({"inline_data": {"mime_type": mime_type or "image/png", "data": encoded}})
                            except Exception: pass
                        else:
                            parts.append({"text": p})
                    elif p.get("type") == "text":
                        parts.append({"text": p["text"]})
                    elif p.get("type") == "image_url":
                        url = p["image_url"]["url"]
                        if url.startswith("data:image"):
                            try:
                                mime_type = url.split(";")[0].split(":")[1]
                                base64_data = url.split(",")[1]
                                parts.append({"inline_data": {"mime_type": mime_type, "data": base64_data}})
                            except Exception: pass
            elif isinstance(content, str) and content.strip():
                # Local file optimization (Images & Video)
                path = content.strip()
                ext = path.lower().split('.')[-1]
                if ext in ('png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'avi', 'webm', 'mkv') and os.path.exists(path):
                    import mimetypes, base64
                    mime_type, _ = mimetypes.guess_type(path)
                    
                    # Fallbacks for common video types if mimetypes fails
                    if not mime_type:
                        if ext == 'mp4': mime_type = 'video/mp4'
                        elif ext == 'mov': mime_type = 'video/quicktime'
                        elif ext == 'webm': mime_type = 'video/webm'
                    
                    try:
                        # Safety check: If file is too large (> 60MB), Gemini might reject inline_data
                        # For now, we assume downloads are limited (we used height<=480 in yt-dlp)
                        file_size = os.path.getsize(path)
                        if file_size < 60 * 1024 * 1024: 
                            with open(path, "rb") as f:
                                encoded = base64.b64encode(f.read()).decode("utf-8")
                                parts.append({"inline_data": {"mime_type": mime_type or "image/png", "data": encoded}})
                        else:
                            parts.append({"text": f"[Media attached but too large for inline: {path}]"})
                    except Exception: pass
                else:
                    parts.append({"text": content})

            # Handle Tool Calls
            if role == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                        parts.append({"function_call": {"name": fn["name"], "args": args}})
                    except Exception: pass

            # Handle Tool Results
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id")
                tool_name = msg.get("name") or find_tool_name(tool_call_id)
                
                # If content is a list [text, media_path], split it to avoid proto errors
                if isinstance(content, list):
                    text_content = content[0]
                    # Part 1: The Function Response Turn
                    history.append({"role": "user", "parts": [{"function_response": {"name": tool_name, "response": {"result": text_content}}}]})
                    
                    # Part 2: A small dummy model thought to maintain user/model alternating chain
                    history.append({"role": "model", "parts": ["I have received the media from the tool. Analyzing now..."]})
                    
                    # Part 3: The Media Turn
                    media_parts = []
                    for p in content[1:]:
                        if isinstance(p, str):
                            path = p.strip()
                            ext = path.lower().split('.')[-1]
                            if ext in ('png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'avi', 'webm', 'mkv') and os.path.exists(path):
                                import mimetypes, base64
                                mime_type, _ = mimetypes.guess_type(path)
                                if not mime_type:
                                    if ext == 'mp4': mime_type = 'video/mp4'
                                    elif ext == 'mov': mime_type = 'video/quicktime'
                                    elif ext == 'webm': mime_type = 'video/webm'
                                try:
                                    with open(path, "rb") as f:
                                        encoded = base64.b64encode(f.read()).decode("utf-8")
                                        media_parts.append({"inline_data": {"mime_type": mime_type or "image/png", "data": encoded}})
                                except Exception: pass
                    
                    if media_parts:
                        # Append the media as a new user turn
                        history.append({"role": "user", "parts": media_parts})
                    
                    continue # Skip the usual history.append at the end of loop
                else:
                    parts.append({"function_response": {"name": tool_name, "response": {"result": content}}})

            if not parts:
                continue

            # MERGING LOGIC: Gemini strictly requires alternating roles. 
            # Sequential messages with the same role MUST be merged into one.
            if pending_role == current_role:
                pending_parts.extend(parts)
            else:
                if pending_role:
                    history.append({"role": pending_role, "parts": pending_parts})
                pending_role = current_role
                pending_parts = parts

        if pending_role:
            history.append({"role": pending_role, "parts": pending_parts})
        
        return system_instruction, history

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to Google Gemini with Tool Support."""
        with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
            f.write(f"\n--- Chat Start: {len(messages)} messages ---\n")
        
        try:
            model_name = model or self._model
            validated_messages = self.validate_messages(messages)
            system_instruction, history = self._convert_messages(validated_messages)
            
            with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                f.write(f"Model: {model_name}\n")
                f.write(f"History roles: {[m['role'] for m in history]}\n")

            # Configure Tools
            gemini_tools = None
            if tools:
                gemini_declarations = []
                for t in tools:
                    try:
                        converted = self._convert_tool_to_gemini(t)
                        if converted:
                            # Validation: Check for empty names/descriptions
                            if not converted.get("name"):
                                with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                                    f.write(f"ERROR: Tool has empty name! Original: {t}\n")
                                continue
                                
                            with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                                f.write(f"Adding tool: {converted['name']} (desc len: {len(converted.get('description',''))})\n")
                            
                            gemini_declarations.append(converted)
                        else:
                            with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                                f.write(f"WARNING: Skipping tool {t.name} (conversion returned None)\n")
                    except Exception as e:
                         with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                                f.write(f"ERROR: Failed to convert tool {t.name}: {e}\n")
                
                if gemini_declarations:
                    gemini_tools = [{"function_declarations": gemini_declarations}]
                    with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                        f.write(f"Configured {len(gemini_declarations)} tools.\n")

            # Create Client
            client = self._genai.GenerativeModel(
                model_name,
                system_instruction=system_instruction,
                tools=gemini_tools
            )

            # Configure Generation
            generation_config = {"temperature": temperature}
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens

            logger.debug(f"Gemini chat: model={model_name}, history={len(history)}")

            # Start Chat Session
            if not history:
                 return LLMResponse("Error: No messages provided", model_name)

            chat_history = history[:-1]
            last_msg_struct = history[-1]
            
            chat = client.start_chat(history=chat_history)
            
            if last_msg_struct["role"] == "user":
                content_to_send = last_msg_struct["parts"]
            elif last_msg_struct["role"] == "function":
                 content_to_send = last_msg_struct["parts"] 
            else:
                 content_to_send = last_msg_struct["parts"]

            try:
                response = await chat.send_message_async(
                    content_to_send,
                    generation_config=generation_config,
                )
            except IndexError:
                # Gemini SDK crashes with IndexError when response has no candidates
                # (e.g., safety block, empty response, connection issue)
                logger.warning("Gemini returned no candidates (IndexError in SDK)")
                return LLMResponse(
                    "I'm sorry, I wasn't able to generate a response. Could you try rephrasing your request?",
                    model_name
                )
            
            # Process Response
            if not response.candidates:
                reason = "No candidates returned"
                if hasattr(response, "prompt_feedback") and response.prompt_feedback.block_reason:
                    reason = f"Blocked by safety filters: {response.prompt_feedback.block_reason}"
                return LLMResponse(f"Error: {reason}", model_name)

            content_text = ""
            tool_calls = []
            
            candidate = response.candidates[0]
            for i, part in enumerate(candidate.content.parts):
                if part.text:
                    content_text += part.text
                if part.function_call:
                    fc = part.function_call
                    args_dict = {}
                    if fc.args:
                        # Convert MapComposite/RepeatedComposite to dict/list
                        for key, value in fc.args.items():
                            args_dict[key] = value
                    
                    # Helper to recursively convert protobuf types and Composites to native Python
                    def to_python(obj):
                        try:
                            # 1. Handle Dict-like (MapComposite / Proto Messages)
                            if hasattr(obj, 'items') and callable(obj.items):
                                return {k: to_python(v) for k, v in obj.items()}
                            
                            # 2. Handle List-like (RepeatedComposite / Iterables)
                            if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
                                return [to_python(x) for x in obj]
                            
                            # 3. Handle specific Protobuf types if needed
                            if hasattr(obj, 'ByteSize'):
                                # This is a proto message
                                return str(obj)
                            
                            return obj
                        except Exception:
                            return str(obj) # Fallback

                    clean_args = {k: to_python(v) for k, v in args_dict.items()}

                    tool_calls.append({
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(clean_args)
                        }
                    })

            # Usage
            usage = {}
            if hasattr(response, "usage_metadata"):
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count,
                }

            return LLMResponse(
                content=content_text,
                model=model_name,
                usage=usage,
                finish_reason="stop",
                raw_response=response,
                tool_calls=tool_calls if tool_calls else None
            )

        except Exception as e:
            import traceback
            err_trace = traceback.format_exc()
            with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                f.write(f"EXCEPTION: {err_trace}\n")
            
            msg = str(e)
            if not msg:
                msg = f"{type(e).__name__}: {repr(e)}"
            logger.error(f"Gemini generation error: {msg}")
            raise Exception(f"Gemini error: {msg}") from e

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response from Gemini."""
        model_name = model or self._model
        validated_messages = self.validate_messages(messages)
        system_instruction, history = self._convert_messages(validated_messages)

        if system_instruction:
            client = self._genai.GenerativeModel(
                model_name,
                system_instruction=system_instruction,
            )
        else:
            client = self._genai.GenerativeModel(model_name)

        chat_history = history[:-1] if len(history) > 1 else []
        chat = client.start_chat(history=chat_history)
        
        last_message = history[-1]["parts"][0] if history else ""
        response = await chat.send_message_async(
            last_message,
            generation_config={"temperature": temperature},
            stream=True,
        )

        async for chunk in response:
            if chunk.text:
                yield chunk.text

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings using Gemini."""
        model_name = model or "text-embedding-004"
        
        texts = [text] if isinstance(text, str) else text
        embeddings = []
        
        for t in texts:
            result = self._genai.embed_content(
                model=f"models/{model_name}",
                content=t,
            )
            embeddings.append(result["embedding"])
        
        return embeddings

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Count tokens using Gemini's tokenizer."""
        model_name = model or self._model
        client = self._genai.GenerativeModel(model_name)
        result = client.count_tokens(text)
        return result.total_tokens
