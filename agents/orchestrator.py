"""
agents/orchestrator.py
----------------------
Ruby – Multi-Agent Orchestrator

Routes tasks to the most capable agent(s), supports parallel execution,
and aggregates/merges results back into a single coherent response.

Routing strategies
------------------
  AUTO       — Ruby's router selects the best agent for the task
  PARALLEL   — all matching agents run simultaneously; results are merged
  SEQUENTIAL — agents run one after another; each sees the previous result
  FIRST_WIN  — parallel, but returns the first successful result

Built-in agents (in-process)
-----------------------------
  general   → GeneralAgent    — general-purpose, uses ModelRouter
  researcher→ ResearchAgent   — web search + summarisation
  coder     → CoderAgent      — code generation + review
  browser   → BrowserAgent    — web browsing via BrowserSession

Usage
-----
    from agents import Orchestrator

    orch = Orchestrator(router=router)
    result = await orch.run("Summarise today's AI news", strategy="AUTO")
    print(result.output)
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Optional

from .base    import BaseAgent, AgentCapability, AgentResult
from .sandbox import AgentSandbox

logger = logging.getLogger("ruby.agents.orchestrator")


# ---------------------------------------------------------------------------
# Routing strategies
# ---------------------------------------------------------------------------

class RoutingStrategy(str, Enum):
    AUTO       = "auto"       # LLM selects best agent
    PARALLEL   = "parallel"   # all capable agents run; merge results
    SEQUENTIAL = "sequential" # chain agents; pass output forward
    FIRST_WIN  = "first_win"  # parallel; first success wins


# ---------------------------------------------------------------------------
# Built-in in-process agents
# ---------------------------------------------------------------------------

class GeneralAgent(BaseAgent):
    name = "general"
    description = "General-purpose reasoning agent using Ruby's primary model."
    capabilities = [AgentCapability.GENERAL]
    sandboxable = False   # shares router — not sandboxable

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        chunks: list[str] = []
        async for chunk in self._router.stream(task):
            chunks.append(chunk)
        return AgentResult(agent_name=self.name, task=task, output="".join(chunks))


class ResearchAgent(BaseAgent):
    name = "researcher"
    description = "Searches the web and synthesises information."
    capabilities = [AgentCapability.RESEARCH, AgentCapability.GENERAL]

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        # Use web_search skill if available via loader, else fallback to router
        from skills.loader import SkillLoader
        loader = SkillLoader()
        loader.load_all()
        search_tool = loader.get_tool("search_web")
        search_result = ""
        if search_tool:
            try:
                search_result = await search_tool.call(query=task)
            except Exception as e:
                logger.warning("[ResearchAgent] search failed: %s", e)

        prompt = (
            f"Research task: {task}\n\n"
            + (f"Search results:\n{search_result}\n\n" if search_result else "")
            + "Please provide a detailed, well-sourced answer."
        )
        chunks: list[str] = []
        async for chunk in self._router.stream(prompt):
            chunks.append(chunk)
        return AgentResult(agent_name=self.name, task=task, output="".join(chunks))


class CoderAgent(BaseAgent):
    name = "coder"
    description = "Writes, reviews, and explains code."
    capabilities = [AgentCapability.CODE, AgentCapability.GENERAL]

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        prompt = (
            "You are an expert software engineer. Respond with clean, well-commented code.\n\n"
            f"Task: {task}"
        )
        if context and context.get("language"):
            prompt = f"Language: {context['language']}\n" + prompt

        chunks: list[str] = []
        async for chunk in self._router.stream(prompt):
            chunks.append(chunk)
        return AgentResult(agent_name=self.name, task=task, output="".join(chunks))


class BrowserAgent(BaseAgent):
    name = "browser"
    description = "Browses the web and extracts information from live pages."
    capabilities = [AgentCapability.BROWSER, AgentCapability.RESEARCH]
    sandboxable = False  # needs display / Chromium process

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        from browser import BrowserSession
        url = context.get("url", "") if context else ""
        try:
            async with BrowserSession(headless=True) as b:
                if url:
                    await b.navigate(url)
                result = await b.instruct(task, router=self._router)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name, task=task, output="",
                error=f"Browser error: {exc}",
            )
        return AgentResult(agent_name=self.name, task=task, output=result)


class SecurityReviewAgent(BaseAgent):
    name = "security_reviewer"
    description = "Reviews code and systems for security vulnerabilities using MITRE ATLAS."
    capabilities = [AgentCapability.SECURITY_REVIEW, AgentCapability.CODE]

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        prompt = (
            "You are a cybersecurity expert focusing on AI system security and MITRE ATLAS.\n"
            "Identify threats, attack vectors, and mitigations.\n\n"
            f"Review request: {task}"
        )
        chunks: list[str] = []
        async for chunk in self._router.stream(prompt):
            chunks.append(chunk)
        return AgentResult(agent_name=self.name, task=task, output="".join(chunks))


# Registry of built-in agent classes
_BUILTIN_AGENTS: dict[str, type[BaseAgent]] = {
    "general":            GeneralAgent,
    "researcher":         ResearchAgent,
    "coder":              CoderAgent,
    "browser":            BrowserAgent,
    "security_reviewer":  SecurityReviewAgent,
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Routes tasks to agents and aggregates their results.

    Parameters
    ----------
    router      : ModelRouter — Ruby's model router
    sandbox     : AgentSandbox | None — for running agents in Docker
    vault       : Vault | None
    default_strategy : RoutingStrategy
    """

    def __init__(
        self,
        router,
        sandbox:          Optional[AgentSandbox]   = None,
        vault                                       = None,
        default_strategy: RoutingStrategy           = RoutingStrategy.AUTO,
    ):
        self._router   = router
        self._sandbox  = sandbox
        self._vault    = vault
        self._strategy = default_strategy
        self._agents:  dict[str, BaseAgent] = {}

        # Register all built-ins
        for name, cls in _BUILTIN_AGENTS.items():
            self.register(cls(router=router, vault=vault))

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.name] = agent
        logger.debug("[Orchestrator] Registered agent: %s", agent.name)

    def unregister(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            return True
        return False

    def get_agent(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def list_agents(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def agents_for(self, capability: AgentCapability) -> list[BaseAgent]:
        return [a for a in self._agents.values() if a.supports(capability)]

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        task:     str,
        strategy: RoutingStrategy | str | None = None,
        context:  dict | None = None,
        agents:   list[str] | None = None,   # explicit agent names to use
    ) -> AgentResult:
        """
        Execute a task using the specified routing strategy.

        Returns a single AgentResult (possibly merged from multiple agents).
        """
        strat = RoutingStrategy(strategy) if isinstance(strategy, str) else (strategy or self._strategy)
        ctx   = context or {}

        # Explicit agent override
        if agents:
            selected = [self._agents[n] for n in agents if n in self._agents]
        elif strat == RoutingStrategy.AUTO:
            selected = await self._auto_select(task, ctx)
        else:
            selected = self.list_agents()

        if not selected:
            selected = [self._agents["general"]]

        logger.info(
            "[Orchestrator] Task routed to: %s (strategy=%s)",
            [a.name for a in selected], strat.value,
        )

        if strat == RoutingStrategy.SEQUENTIAL:
            return await self._run_sequential(task, selected, ctx)
        elif strat == RoutingStrategy.FIRST_WIN:
            return await self._run_first_win(task, selected, ctx)
        elif strat in (RoutingStrategy.PARALLEL, RoutingStrategy.AUTO) and len(selected) > 1:
            return await self._run_parallel(task, selected, ctx)
        else:
            return await selected[0].run(task, ctx)

    # ------------------------------------------------------------------
    # Routing strategies
    # ------------------------------------------------------------------

    async def _auto_select(self, task: str, ctx: dict) -> list[BaseAgent]:
        """Ask the model which agent to use, falling back to 'general'."""
        agent_descriptions = "\n".join(
            f"  {a.name}: {a.description}" for a in self.list_agents()
        )
        prompt = (
            f"Given this task, which agent should handle it?\n"
            f"Task: {task}\n\n"
            f"Available agents:\n{agent_descriptions}\n\n"
            "Reply with ONLY the agent name (one word). If unsure, reply: general"
        )
        chunks: list[str] = []
        async for chunk in self._router.stream(prompt):
            chunks.append(chunk)
        agent_name = "".join(chunks).strip().split()[0].lower()
        agent = self._agents.get(agent_name, self._agents["general"])
        return [agent]

    async def _run_parallel(
        self, task: str, agents: list[BaseAgent], ctx: dict
    ) -> AgentResult:
        """Run all agents in parallel and merge results."""
        tasks = [asyncio.create_task(a.run(task, ctx)) for a in agents]
        results: list[AgentResult] = await asyncio.gather(*tasks, return_exceptions=False)
        successful = [r for r in results if r.success]
        if not successful:
            return results[0]  # return first error

        combined_output = "\n\n---\n\n".join(
            f"**{r.agent_name}:**\n{r.output}" for r in successful
        )
        # Let the model synthesise a final answer
        if len(successful) > 1:
            synth_prompt = (
                f"Multiple AI agents analysed this task: {task}\n\n"
                f"Their responses:\n\n{combined_output}\n\n"
                "Synthesise the best combined answer."
            )
            chunks: list[str] = []
            async for chunk in self._router.stream(synth_prompt):
                chunks.append(chunk)
            combined_output = "".join(chunks)

        return AgentResult(
            agent_name="orchestrator",
            task=task,
            output=combined_output,
            metadata={"agents_used": [r.agent_name for r in successful]},
        )

    async def _run_sequential(
        self, task: str, agents: list[BaseAgent], ctx: dict
    ) -> AgentResult:
        """Run agents one after another, passing each result into the next."""
        result = AgentResult(agent_name="", task=task, output="")
        for agent in agents:
            sequential_ctx = {**ctx, "previous_result": result.output}
            result = await agent.run(task, sequential_ctx)
            if not result.success:
                break
        return result

    async def _run_first_win(
        self, task: str, agents: list[BaseAgent], ctx: dict
    ) -> AgentResult:
        """Run agents in parallel; return the first successful result."""
        queue: asyncio.Queue[AgentResult] = asyncio.Queue()

        async def _run_and_enqueue(agent: BaseAgent):
            r = await agent.run(task, ctx)
            await queue.put(r)

        tasks = [asyncio.create_task(_run_and_enqueue(a)) for a in agents]
        result: AgentResult | None = None
        for _ in agents:
            r = await queue.get()
            if r.success and result is None:
                result = r
        for t in tasks:
            t.cancel()
        return result or AgentResult(
            agent_name="orchestrator", task=task, output="",
            error="All agents failed.",
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "agents":   [a.name for a in self.list_agents()],
            "strategy": self._strategy.value,
            "sandbox":  self._sandbox is not None,
        }
