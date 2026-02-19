"""Main agent controller implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import tempfile
import os
from datetime import datetime
from typing import AsyncGenerator, Any

from config.settings import Settings
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.state import ConversationState
from src.agent.tools import Tool
from src.agent.builtins.filesystem import FILESYSTEM_TOOLS
from src.agent.builtins.web import WEB_TOOLS
from src.agent.builtins.email_tools import EMAIL_TOOLS
from src.agent.builtins.video import VIDEO_TOOLS
from src.agent.builtins.vision import VISION_TOOLS
from src.agent.builtins.vision_pro import VISION_PRO_TOOLS
from src.agent.builtins.canvas import CANVAS_TOOLS
from src.agent.builtins.testing import TESTING_TOOLS
from src.agent.builtins.pdf import PDF_TOOLS
from src.agent.builtins.creative import CREATIVE_TOOLS
from src.agent.scheduler import Scheduler
from src.llm.factory import ProviderFactory
from src.llm.base import LLMProvider
from src.memory.client import MemoryClient
from src.memory.utils import format_memory_string
from src.agent.monitor import RubyMonitor

logger = logging.getLogger(__name__)


class AgentController:
    """Orchestrates the agent loop, memory, and LLM interactions."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider | None = None,
        memory: MemoryClient | None = None,
        tools: list[Tool] | None = None,
        event_callback: callable | None = None,
    ):
        """Initialize the agent controller.
        
        Args:
            settings: configurations
            llm: Optional pre-configured LLM provider
            memory: Optional pre-configured memory client
            tools: List of tools available to the agent
            event_callback: Async function to broadcast events
        """
        self._settings = settings
        self._llm = llm or ProviderFactory.create(settings=settings)
        self._memory = memory or MemoryClient(settings)
        self._event_callback = event_callback
        
        # Tools: Load built-in FS tools + Web tools + Email tools + custom ones
        self._tools = tools or []
        self._tools.extend(FILESYSTEM_TOOLS)
        self._tools.extend(WEB_TOOLS)
        self._tools.extend(EMAIL_TOOLS)
        self._tools.extend(VIDEO_TOOLS)
        self._tools.extend(VISION_TOOLS)
        self._tools.extend(VISION_PRO_TOOLS)
        self._tools.extend(CANVAS_TOOLS)
        self._tools.extend(TESTING_TOOLS)
        self._tools.extend(PDF_TOOLS)
        self._tools.extend(CREATIVE_TOOLS)
        self._tool_map = {t.name: t for t in self._tools}
        
        # Scheduler
        self._scheduler = Scheduler()
        
        # State management (single session for now, could expand to map)
        self._session_id = str(uuid.uuid4())
        
        # Determine history path
        history_dir = os.path.join(self._settings.data_dir, "history")
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, "chat_history.json")

        self._state = ConversationState(
            session_id=self._session_id,
            user_id="default_user",  # Could be parameterized
            persistence_path=history_path
        )
        
        # Router LLM for hybrid mode
        self._router_llm: LLMProvider | None = None
        
        # Background tasks
        self._tasks: set[asyncio.Task] = set()
        
        # Monitor
        self._monitor = RubyMonitor(event_callback=event_callback)

        logger.info(f"Agent initialized with provider: {self._llm.name} ({self._llm.current_model})")
        if self._settings.hybrid_routing:
            logger.info(f"Hybrid routing enabled using: {self._settings.hybrid_routing_model}")
        logger.info(f"Tools available: {list(self._tool_map.keys())}")

    @property
    def provider_name(self) -> str:
        """Get current provider name."""
        return self._llm.name

    def switch_provider(self, provider_name: str, model: str | None = None) -> None:
        """Switch the active LLM provider.
        
        Args:
            provider_name: Name of provider (openai, anthropic, etc.)
            model: Optional model name
        """
        logger.info(f"Switching provider to {provider_name}")
        self._llm = ProviderFactory.create(
            provider_name=provider_name,
            model=model,
            settings=self._settings
        )

    def clear_history(self) -> None:
        """Clear the current conversation history."""
        self._state.clear()

    async def start_service(self) -> None:
        """Start the agent's background services (scheduler)."""
        logger.info("Starting agent services...")
        
        # Helper to process background tasks without persisting to user history
        async def run_bg_task(instruction: str):
            logger.info(f"Running background task: {instruction}")
            try:
                # We don't persist to main chat history to keep it clean, 
                # but we SHOULD persist to memory (which process() does via _memorize_background)
                response = await self.process(instruction, persist=False)
                
                # Proactive Notification: If we have a result and a callback, tell the user!
                if self._event_callback and response:
                    await self._event_callback("proactive", {
                        "task": instruction[:50] + "...",
                        "result": response
                    })
            except Exception as e:
                logger.error(f"Background task failed: {e}")

        # 1. Email Cleanup (Hourly)
        self.schedule_task(
            task="Perform a thorough autonomous cleanup of my Gmail. Check 'INBOX', '[Gmail]/Spam', and '[Gmail]/Promotions'. Identify marketing junk and spam. Only delete if 100% sure.",
            interval=self._settings.email_cleanup_interval
        )
        
        # 2. Environment Discovery (Getting to know the user's files)
        self.schedule_task(
            task="Explore my local files in 'C:/Users/grind/OneDrive/Documents' and 'C:/Users/grind/OneDrive/Desktop'. List recent files and summarize what projects or interests I seem focused on. Save this summary as a memory of my 'Current Context'.",
            interval=self._settings.discovery_interval
        )
        
        # 3. Self-Reflection (Learning habits and preferences)
        self.schedule_task(
            task="Deep Reflection: Analyze our recent conversation history and any observations from my files. Identify my habits, preferences, mood, and workload. Update my 'Deep Profile' memory with these insights so you can be more supportive and proactive.",
            interval=self._settings.reflection_interval
        )
        
        # 4. Start Monitoring
        await self._monitor.start()
        self._monitor.update_state(goal="Agent Started", tool="Idle", context="Services active")

        await self._scheduler.start(run_bg_task)

    def stop_service(self) -> None:
        """Stop agent services."""
        self._scheduler.stop()
        self._monitor.stop()

    def schedule_task(self, task: str, interval: int) -> None:
        """Schedule a task for the agent to do periodically.
        
        Args:
            task: Instruction for the agent
            interval: Interval in seconds
        """
        self._scheduler.add_job(task, interval)

    async def flow_process(self, user_input: str) -> str:
        # Renamed old 'process' to avoid confusion if we want to add middleware
        # But for now, keeping 'process' as main entry point is fine
        return await self.process(user_input)

    async def _memorize_background(self, messages: list[dict[str, str]]) -> None:
        """Background task to save recent interaction to memory.
        
        Ruby expects a file resource. We'll dump the messages to a temporary JSON file.
        """
        try:
            # Create a temp file for the conversation segment
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump(messages, f, indent=2)
                temp_path = f.name
            
            # Send to Ruby
            await self._memory.memorize(
                content=temp_path,
                modality="conversation",
                user_id=self._state.user_id,
            )
            
            # Cleanup (optional - Ruby might need it for a bit, but ideally it consumes it)
            # In a real app we might manage these temp files better
            # For now, let's assume valid "resource_url" behavior
            # os.unlink(temp_path) # memU processes it async, so don't delete immediately if relying on path
            
        except Exception as e:
            logger.error(f"Background memorization failed: {e}")

    async def process(self, user_input: str, images: list[str] | None = None, persist: bool = True) -> str:
        """Process a single user input and return response.
        
        Flow (ReAct / Tool Loop):
        1. Retrieve relevant memories (RAG)
        2. Build Initial Prompt
        3. Loop:
            a. Call LLM with current messages + tools
            b. If text content -> Add to messages
            c. If tool calls -> Execute tools -> Add results to messages -> Continue Loop
            d. If finish_reason is stop and no tool calls -> Break
        4. Trigger Memorization
        5. Return final response
        """
        logger.info(f"Processing input: {user_input[:50]}...")
        
        # 1. Retrieve Memories
        # Use 'rag' for fast retrieval, but allow for 'llm' for deeper context if the query is complex
        retrieval_method = "llm" if len(user_input.split()) > 20 else "rag"
        logger.info(f"Recalling memories using method: {retrieval_method}")
        
        memories = await self._memory.recall(
            query=user_input,
            user_id=self._state.user_id,
        )
        memory_str = format_memory_string(memories.get("items", {}) if hasattr(memories, "get") else {})
        
        # 2. Build Prompt
        system_msg = SYSTEM_PROMPT.format(
            agent_name=self._settings.agent_name,
            memory_context=memory_str or "No relevant past memories found."
        )
        
        messages = [{"role": "system", "content": system_msg}]
        messages.extend(self._state.get_context_window(self._settings.agent_max_history))
        
        # 2.4 Log Restart for Debug
        with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
            f.write(f"\n--- RESTART DETECTED: Agent processing fresh turn ---\n")

        # 2.5 Forced Intervention: If a video URL is present, remind the agent to use the tool
        video_patterns = ["youtube.com", "youtu.be", "vimeo.com", ".mp4", ".mov"]
        if any(p in user_input.lower() for p in video_patterns):
            messages.append({
                "role": "system", 
                "content": "CRITICAL: A video link was detected. You MUST use the `watch_video` tool immediately to see the frames. Do NOT apologize or say you are watching in the background WITHOUT calling the tool."
            })
        
        # Multimodal handling
        if images:
            content = [{"type": "text", "text": user_input}]
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img}
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_input})
        
        final_response_content = ""
        iteration = 0
        MAX_ITERATIONS = 10 
        
        # 3. Execution Loop
        while iteration < MAX_ITERATIONS:
            # Determine which LLM to use
            active_llm = self._llm
            if self._settings.hybrid_routing:
                if self._router_llm is None:
                    try:
                        self._router_llm = ProviderFactory.create(
                            "ollama", 
                            model=self._settings.hybrid_routing_model, 
                            settings=self._settings
                        )
                    except Exception as e:
                        logger.error(f"Failed to init router LLM: {e}")
                        self._settings.hybrid_routing = False # Fallback
                
                if self._settings.hybrid_routing:
                    active_llm = self._router_llm
            
            # Call LLM with low temperature for better tool following
            response = await active_llm.chat(messages, tools=self._tools, temperature=0.0)
            content = response.content
            tool_calls = response.tool_calls
            
            # If we used the router and it gave NO tool calls AND NO content,
            # or if it gave content, we might want the primary LLM to take over 
            # for a better response.
            if self._settings.hybrid_routing and not tool_calls:
                # If router performed no actions, let primary LLM handle it
                # We don't append the router's empty response to history yet
                response = await self._llm.chat(messages, tools=self._tools)
                content = response.content
                tool_calls = response.tool_calls
            
            # Add assistant response to history
            msg_dict = {"role": "assistant", "content": content}
            if tool_calls:
                # If there are tool calls, we must store them exactly as the provider expects
                # For OpenAI, this means including the 'tool_calls' field in the message
                # We need to adapt our simple dict structure if we want to be fully robust,
                # but for now let's assume our state manager can handle 'tool_calls' or we append raw
                msg_dict["tool_calls"] = tool_calls
            
            messages.append(msg_dict)
            
            if content:
                final_response_content = content # Keep track of latest text
            
            # If no tool calls, we are done
            if not tool_calls:
                break
                
            # Execute Tools
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                _id = tc["id"]
                args_str = tc["function"]["arguments"]
                
                logger.info(f"Executing tool: {func_name} with args: {args_str}")
                
                try:
                    args = json.loads(args_str)
                    if func_name in self._tool_map:
                        result = await self._tool_map[func_name](**args)
                        result_str = str(result)
                        logger.info(f"Tool output: {result_str[:200]}...") # Log preview
                    else:
                        result_str = f"Error: Tool {func_name} not found."
                except Exception as e:
                    result_str = f"Error executing tool {func_name}: {e}"
                
                # Add tool result
                messages.append({
                    "role": "tool",
                    "tool_call_id": _id,
                    "content": result_str
                })
                
            iteration += 1
            
        # 4. Update State (Persist only the user input and FINAL answer for now to keep history clean?)
        # Ideally we persist the whole chain, but our current State Manager is simple.
        # Let's save the simple turn for readability, or the whole chain if we want full context.
        # For this PoC, let's just save the user input and the final text response.
        if persist:
            self._state.add_message("user", user_input)
            self._state.add_message("assistant", final_response_content)
        
        # 5. Trigger Memorization
        turn = [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": final_response_content}
        ]
        task = asyncio.create_task(self._memorize_background(turn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        
        return final_response_content

    async def stream_events(self, user_input: str, images: list[str] | None = None, persist: bool = True) -> AsyncGenerator[dict[str, Any], None]:
        """Process input and stream events (thoughts, tools, content)."""
        yield {"type": "thinking", "content": "Initializing..."}
        
        # 1. Retrieve
        try:
            logger.info("Recalling memories...")
            self._monitor.update_state(goal="Thinking", tool="Memory Recall", context=f"Query: {user_input[:20]}...")
            memories = await self._memory.recall(user_input, self._state.user_id)
            memory_str = format_memory_string(memories.get("items", {}) if hasattr(memories, "get") else {})
            self._monitor.update_state(context="Memories retrieved")
        except Exception as e:
            logger.error(f"Memory recall failed: {e}")
            memory_str = ""
        
        # 2. Build Prompt
        yield {"type": "thinking", "content": "Preparing prompt..."}
        system_msg = SYSTEM_PROMPT.format(
            agent_name=self._settings.agent_name,
            memory_context=memory_str or "No relevant past memories found."
        )
        
        messages = [{"role": "system", "content": system_msg}]
        messages.extend(self._state.get_context_window(self._settings.agent_max_history))
        
        # Multimodal handling
        if images:
            content = [{"type": "text", "text": user_input}]
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img}
                })
            messages.append({"role": "user", "content": content})
            if persist:
                self._state.add_message("user", content)
        else:
            messages.append({"role": "user", "content": user_input})
            if persist:
                self._state.add_message("user", user_input)
        
        iteration = 0
        MAX_ITERATIONS = 5
        final_content = ""
        
        logger.info(f"Starting execution loop for: {user_input[:50]}...")
        
        while iteration < MAX_ITERATIONS:
            # Yield thinking event
            yield {"type": "thinking", "content": f"Iteration {iteration+1}..."}
            
            self._monitor.update_state(goal=f"Processing: {user_input[:30]}", tool="Thinking", context=f"Iteration {iteration+1}")
            
            # Determine which LLM to use
            active_llm = self._llm
            if self._settings.hybrid_routing:
                if self._router_llm is None:
                    try:
                        self._router_llm = ProviderFactory.create(
                            "ollama", 
                            model=self._settings.hybrid_routing_model, 
                            settings=self._settings
                        )
                    except:
                        self._settings.hybrid_routing = False
                
                if self._settings.hybrid_routing:
                    active_llm = self._router_llm

            # Call LLM with timeout and retry logic
            try:
                # Add a reasonable timeout for the chat call
                timeout = 15 if self._settings.hybrid_routing and active_llm == self._router_llm else 60
                logger.info(f"Calling LLM: {active_llm.name} ({active_llm.current_model}) with timeout {timeout}s")
                response = await asyncio.wait_for(active_llm.chat(messages, tools=self._tools), timeout=timeout)
            except (asyncio.TimeoutError, Exception) as e:
                # If we hit an error (timeout or connection failure) and we're using the router, fail over
                if self._settings.hybrid_routing and active_llm == self._router_llm:
                    error_type = "Timeout" if isinstance(e, asyncio.TimeoutError) else "Connection Failure"
                    logger.warning(f"Hybrid Router {active_llm.name} {error_type} ({e}). Falling back to primary LLM...")
                    
                    yield {
                        "type": "thinking", 
                        "content": f"Local brain ({active_llm.current_model}) is offline or timed out. Falling back to primary model ({self._llm.name})..."
                    }
                    
                    self._settings.hybrid_routing = False # Disable for this turn
                    active_llm = self._llm
                    
                    try:
                        logger.info(f"Fallback attempt: {active_llm.name} ({active_llm.current_model})")
                        response = await active_llm.chat(messages, tools=self._tools)
                    except Exception as fallback_err:
                        logger.error(f"Fallback LLM {active_llm.name} failed: {fallback_err}")
                        yield {
                            "type": "error", 
                            "content": f"CRITICAL: Both local brain and cloud fallback ({active_llm.name}) failed. Error: {fallback_err}"
                        }
                        break
                else:
                    # If this was already the primary LLM, or hybrid routing wasn't in dev mode, report the error
                    logger.error(f"Primary LLM {active_llm.name} error: {e}")
                    error_msg = str(e)
                    if "All connection attempts failed" in error_msg:
                        error_msg = f"Could not connect to {active_llm.name}. Please check your internet connection or API keys."
                    yield {"type": "error", "content": f"AI Provider Error ({active_llm.name}): {error_msg}"}
                    break
            
            content = response.content
            tool_calls = response.tool_calls

            # If router had nothing to say and no tools, use primary
            if self._settings.hybrid_routing and not tool_calls:
                yield {"type": "thinking", "content": "Router finished, getting final response..."}
                response = await self._llm.chat(messages, tools=self._tools)
                content = response.content
                tool_calls = response.tool_calls
            
            # Add to history
            msg_dict = {"role": "assistant", "content": content}
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            messages.append(msg_dict)
            
            if persist:
                self._state.add_message("assistant", content, tool_calls=tool_calls)
            
            # Yield content if present
            if content:
                final_content = content
                yield {"type": "content", "content": content}
            
            if not tool_calls:
                break
                
            # Execute Tools
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                _id = tc["id"]
                
                yield {
                    "type": "tool_start", 
                    "tool": func_name, 
                    "args": args_str
                }
                
                self._monitor.update_state(tool=func_name, context=f"Args: {args_str[:30]}...")
                
                try:
                    args = json.loads(args_str)
                    if func_name in self._tool_map:
                        result = await self._tool_map[func_name](**args)
                        result_str = str(result)
                        
                        # Canvas Integration: Check for visual updates
                        if isinstance(result, str) and result.startswith('{'):
                            try:
                                data = json.loads(result)
                                if "__canvas__" in data:
                                    yield {"type": "canvas_update", "content": data["__canvas__"]}
                                    
                                    # If the tool provides specific content for the LLM, use that
                                    if "__llm_content__" in data:
                                        media_path = data.get("__media__", {}).get("path")
                                        if media_path:
                                            # Return a list [text, path] - our provider now handles this
                                            result_str = [data["__llm_content__"], media_path]
                                            with open(r"C:\Users\grind\Desktop\gemini_debug.txt", "a") as f:
                                                f.write(f"DEBUG: Formatted multimodal result list: {result_str[0][:50]}... + {media_path}\n")
                                        else:
                                            result_str = data["__llm_content__"]
                                    elif "__media__" in data:
                                        # Only media, no explicit text? Just use path.
                                        result_str = data["__media__"]["path"]
                                    else:
                                        # Otherwise, tell LLM it was rendered
                                        result_str = "Content successfully rendered to the user's Canvas workspace."
                            except Exception as e:
                                logger.warning(f"Failed to parse canvas update from tool output: {e}")
                                # continue without yielding canvas update
                    else:
                        result_str = f"Error: Tool {func_name} not found."
                except Exception as e:
                    result_str = f"Error: {e}"
                
                yield {
                    "type": "tool_end",
                    "tool": func_name,
                    "output": result_str[0] if isinstance(result_str, list) else result_str
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": _id,
                    "content": result_str
                })
                
                if persist:
                    self._state.add_message("tool", result_str, tool_call_id=_id)
            
            iteration += 1

        # Update State - handled incrementally now
        
        # Memorize
        turn = [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": final_content}
        ]
        task = asyncio.create_task(self._memorize_background(turn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        
        # Auto-Save high-res screenshot of the completed work
        if final_content and iteration > 0:
             screenshot_path = await self._monitor.capture_high_res()
             yield {"type": "content", "content": f"\n\n*[System: Auto-saved work state to {screenshot_path}]*"}
        
        self._monitor.update_state(goal="Work Complete", tool="Idle", context="Waiting for user")
        yield {"type": "done"}
