"""
agents/base.py
--------------
Ruby – Multi-Agent System: Base Agent Contract

Defines the `Agent` abstract base class that all specialized agents implement.

An Agent is an autonomous reasoning unit that:
  - Accepts a task (prompt + optional context dict)
  - Returns a structured result (text + metadata)
  - May call tools, browse the web, or invoke sub-agents

Agents can be:
  - In-process (run in the same Python process as Ruby)
  - Sandboxed (run inside a Docker container via agents/sandbox.py)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """The output of a completed agent run."""
    agent_name: str
    task:       str
    output:     str
    confidence: float = 1.0          # 0.0–1.0, agent's self-reported confidence
    metadata:   dict  = field(default_factory=dict)
    error:      str   = ""           # non-empty if the agent failed
    tokens_used: int  = 0

    @property
    def success(self) -> bool:
        return not self.error


# ---------------------------------------------------------------------------
# AgentCapability — what an agent is good at
# ---------------------------------------------------------------------------

class AgentCapability(str, Enum):
    GENERAL          = "general"          # General-purpose reasoning
    CODE             = "code"             # Code generation, debugging, review
    RESEARCH         = "research"         # Web search, summarisation, fact-checking
    BROWSER          = "browser"          # Web browsing + form filling
    DATA_ANALYSIS    = "data_analysis"    # Data wrangling, stats, charts
    IMAGE_ANALYSIS   = "image_analysis"   # Visual understanding
    SCHEDULING       = "scheduling"       # Calendar, reminders, cron
    SECURITY_REVIEW  = "security_review"  # Threat analysis, MITRE ATLAS


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Abstract base class for all Ruby agents.

    Subclass and implement `run()`.  Optionally override `stream()` for
    streaming output support.
    """

    #: One-word identifier, e.g. "researcher", "coder"
    name: str = "base"

    #: Human-readable description
    description: str = "Base agent"

    #: What this agent specialises in
    capabilities: list[AgentCapability] = [AgentCapability.GENERAL]

    #: Whether this agent can be safely sandboxed in Docker
    sandboxable: bool = True

    def __init__(self, router=None, vault=None):
        self._router = router
        self._vault  = vault

    @abstractmethod
    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        """
        Execute the task and return a result.

        Parameters
        ----------
        task    : str   — natural-language task description
        context : dict  — optional shared context (caller may pass results from
                          other agents, user profile, conversation history, etc.)
        """
        ...

    async def stream(
        self, task: str, context: dict | None = None
    ) -> AsyncIterator[str]:
        """
        Streaming version of run().  Yields response chunks.
        Default implementation runs `run()` and yields the output as a single chunk.
        Override for true streaming.
        """
        result = await self.run(task, context)
        yield result.output

    def supports(self, capability: AgentCapability) -> bool:
        return capability in self.capabilities

    def __repr__(self) -> str:
        return f"<Agent name={self.name!r} caps={[c.value for c in self.capabilities]}>"
