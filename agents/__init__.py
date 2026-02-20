"""
agents/__init__.py
------------------
Ruby – Multi-Agent Routing System

Provides a task orchestrator that routes work to specialised AI agents,
supports parallel and sequential routing, and optionally runs agents inside
Docker containers for isolation.

Public API
----------
    from agents import (
        Orchestrator,
        AgentSandbox,
        BaseAgent,
        AgentCapability,
        AgentResult,
        RoutingStrategy,
    )

Built-in agents
---------------
  general            General-purpose reasoning (ModelRouter)
  researcher         Web search + synthesis (DuckDuckGo + router)
  coder              Code generation, review, and explanation
  browser            Live web browsing via BrowserSession
  security_reviewer  MITRE ATLAS threat analysis

Quick-start
-----------
    from agents import Orchestrator
    from models import ModelRouter

    router = ModelRouter()
    orch   = Orchestrator(router=router)

    # Auto-route a task
    result = await orch.run("Write a Python function that sorts a list of dicts by key")
    print(result.output)

    # Run specific agents in parallel
    result = await orch.run(
        "What are the security risks of using eval() in Python?",
        agents=["researcher", "security_reviewer"],
        strategy="parallel",
    )
    print(result.output)

    # Register a custom agent
    class MyAgent(BaseAgent):
        name = "my_agent"
        capabilities = [AgentCapability.GENERAL]

        async def run(self, task, context=None):
            ...

    orch.register(MyAgent(router=router))

Docker sandboxing
-----------------
    sandbox = AgentSandbox(image="ruby-agent:latest", network="none")
    orch    = Orchestrator(router=router, sandbox=sandbox)
"""

from .base         import BaseAgent, AgentCapability, AgentResult
from .orchestrator import Orchestrator, RoutingStrategy
from .sandbox      import AgentSandbox

__all__ = [
    "BaseAgent",
    "AgentCapability",
    "AgentResult",
    "Orchestrator",
    "RoutingStrategy",
    "AgentSandbox",
]
