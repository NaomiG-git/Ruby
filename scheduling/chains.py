"""
scheduling/chains.py
--------------------
Ruby – Automation Chains

Multi-step workflows that link skills, AI prompts, channel actions, webhook
calls, and conditional logic. Chains are defined programmatically (or via
stored JSON) and executed step-by-step, with the output of each step passed
as context to the next.

Step types
----------
  prompt      — send a prompt to Ruby's ModelRouter; result stored in context
  webhook     — call a registered outbound webhook
  send        — send a message to a channel
  condition   — branch based on a context value (if/else)
  wait        — pause for N seconds
  set         — set a context variable to a literal value

Usage
-----
    from scheduling.chains import ChainBuilder, ChainRunner

    builder = ChainBuilder("daily_report")
    builder.prompt("summarise", "Give me a 3-bullet daily summary of my tasks.")
    builder.send("report", channel="telegram", chat_id="+1234567890", text="{{summarise}}")
    builder.webhook("slack_notify", webhook="notify_slack", context={"message": "{{summarise}}"})

    runner = ChainRunner(router=router, channel_mgr=mgr, webhook_server=ws)
    await runner.run(builder.build())
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger("ruby.scheduling.chains")


# ---------------------------------------------------------------------------
# Step dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Step:
    type:    str           # "prompt" | "send" | "webhook" | "condition" | "wait" | "set"
    name:    str           # step name (also used as context key for result storage)
    config:  dict = field(default_factory=dict)

    # For condition steps
    then_steps: list["Step"] = field(default_factory=list)
    else_steps: list["Step"] = field(default_factory=list)


@dataclass
class Chain:
    name:         str
    steps:        list[Step] = field(default_factory=list)
    description:  str  = ""
    created_at:   float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# ChainBuilder — fluent API
# ---------------------------------------------------------------------------

class ChainBuilder:
    """
    Fluent builder for automation chains.

    Example
    -------
        chain = (
            ChainBuilder("morning_brief")
            .prompt("news",    "Summarise today's tech news in 3 points.")
            .prompt("weather", "What's the weather forecast for London today?")
            .send("brief", channel="telegram", chat_id="+1234567890",
                  text="🌅 Morning brief:\n\n**News:**\n{{news}}\n\n**Weather:**\n{{weather}}")
            .build()
        )
    """

    def __init__(self, name: str, description: str = ""):
        self._chain = Chain(name=name, description=description)

    def prompt(self, name: str, prompt: str, model: Optional[str] = None, use_history: bool = False) -> "ChainBuilder":
        """Run *prompt* through Ruby's router and store the result as {{name}}."""
        self._chain.steps.append(Step(
            type="prompt", name=name,
            config={"prompt": prompt, "model": model, "use_history": use_history},
        ))
        return self

    def send(self, name: str, channel: str, chat_id: str, text: str) -> "ChainBuilder":
        """Send *text* (with {{var}} substitution) to *channel*:*chat_id*."""
        self._chain.steps.append(Step(
            type="send", name=name,
            config={"channel": channel, "chat_id": chat_id, "text": text},
        ))
        return self

    def webhook(self, name: str, webhook: str, context: Optional[dict] = None) -> "ChainBuilder":
        """Call a registered outbound webhook with optional *context* dict (supports {{var}} in values)."""
        self._chain.steps.append(Step(
            type="webhook", name=name,
            config={"webhook": webhook, "context": context or {}},
        ))
        return self

    def wait(self, name: str, seconds: float) -> "ChainBuilder":
        """Pause for *seconds* before continuing."""
        self._chain.steps.append(Step(type="wait", name=name, config={"seconds": seconds}))
        return self

    def set_var(self, name: str, value: Any) -> "ChainBuilder":
        """Set context variable {{name}} to a literal *value*."""
        self._chain.steps.append(Step(type="set", name=name, config={"value": value}))
        return self

    def condition(
        self,
        name:       str,
        expression: str,           # e.g. "{{status}} == 'ok'"
        then_steps: "ChainBuilder",
        else_steps: Optional["ChainBuilder"] = None,
    ) -> "ChainBuilder":
        """Branch execution based on a simple expression evaluated against the context."""
        self._chain.steps.append(Step(
            type="condition",
            name=name,
            config={"expression": expression},
            then_steps=then_steps._chain.steps,
            else_steps=(else_steps._chain.steps if else_steps else []),
        ))
        return self

    def build(self) -> Chain:
        return deepcopy(self._chain)


# ---------------------------------------------------------------------------
# Template rendering (re-use from webhooks module)
# ---------------------------------------------------------------------------

import re as _re

_TEMPLATE_RE = _re.compile(r"\{\{([\w.]+)\}\}")


def _render(template: str, ctx: dict) -> str:
    def replace(m: _re.Match) -> str:
        path  = m.group(1).split(".")
        value = ctx
        for part in path:
            value = value.get(part, "") if isinstance(value, dict) else ""
        return str(value)
    return _TEMPLATE_RE.sub(replace, str(template))


def _render_dict(d: dict, ctx: dict) -> dict:
    """Recursively render all string values in *d* using *ctx*."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _render(v, ctx)
        elif isinstance(v, dict):
            result[k] = _render_dict(v, ctx)
        else:
            result[k] = v
    return result


def _eval_expression(expression: str, ctx: dict) -> bool:
    """
    Evaluate a simple condition expression against the context.
    Supports: ==, !=, contains, not contains, truthy check.
    e.g. "{{status}} == 'ok'"  or  "{{message}} contains 'error'"
    """
    rendered = _render(expression, ctx)
    rendered = rendered.strip()

    # "X contains Y"
    m = _re.match(r"^(.+?)\s+contains\s+(.+)$", rendered, _re.I)
    if m:
        return m.group(2).strip().strip("'\"") in m.group(1).strip()

    # "X not contains Y"
    m = _re.match(r"^(.+?)\s+not\s+contains\s+(.+)$", rendered, _re.I)
    if m:
        return m.group(2).strip().strip("'\"") not in m.group(1).strip()

    # "X == Y"
    m = _re.match(r"^(.+?)\s*==\s*(.+)$", rendered)
    if m:
        return m.group(1).strip().strip("'\"") == m.group(2).strip().strip("'\"")

    # "X != Y"
    m = _re.match(r"^(.+?)\s*!=\s*(.+)$", rendered)
    if m:
        return m.group(1).strip().strip("'\"") != m.group(2).strip().strip("'\"")

    # Truthy check
    return bool(rendered) and rendered.lower() not in ("false", "0", "none", "null", "")


# ---------------------------------------------------------------------------
# ChainRunner — executes Chain instances
# ---------------------------------------------------------------------------

class ChainRunner:
    """
    Executes automation chains step by step.

    Parameters
    ----------
    router         : ModelRouter
    channel_mgr    : ChannelManager | None
    webhook_server : WebhookServer | None
    vault          : Vault | None — for stored chain persistence
    """

    STORE_KEY = "automation_chains"

    def __init__(
        self,
        router,
        channel_mgr=None,
        webhook_server=None,
        vault=None,
    ):
        self._router    = router
        self._channel   = channel_mgr
        self._webhooks  = webhook_server
        self._vault     = vault or self._default_vault()
        self._chains:   dict[str, Chain] = {}
        self._load()

    # ------------------------------------------------------------------
    # Chain management
    # ------------------------------------------------------------------

    def store_chain(self, chain: Chain) -> None:
        """Persist a chain so it can be retrieved and run later by name."""
        self._chains[chain.name] = chain
        self._save()

    def get_chain(self, name: str) -> Chain:
        return self._chains[name]

    def list_chains(self) -> list[str]:
        return list(self._chains.keys())

    def delete_chain(self, name: str) -> None:
        del self._chains[name]
        self._save()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(self, chain: Chain, initial_context: Optional[dict] = None) -> dict:
        """
        Execute *chain* and return the final context dict.

        Parameters
        ----------
        chain           : Chain      — the chain to execute
        initial_context : dict | None — seed context values
        """
        ctx = dict(initial_context or {})
        logger.info("[Chains] Starting chain: %s (%d steps)", chain.name, len(chain.steps))
        await self._run_steps(chain.steps, ctx)
        logger.info("[Chains] Chain complete: %s", chain.name)
        return ctx

    async def run_by_name(self, name: str, initial_context: Optional[dict] = None) -> dict:
        """Look up a stored chain by name and run it."""
        chain = self._chains.get(name)
        if not chain:
            raise KeyError(f"No chain named: {name!r}")
        return await self.run(chain, initial_context)

    async def _run_steps(self, steps: list[Step], ctx: dict) -> None:
        for step in steps:
            try:
                await self._run_step(step, ctx)
            except Exception as exc:
                logger.exception("[Chains] Step %r failed: %s", step.name, exc)
                ctx[f"{step.name}__error"] = str(exc)
                # Continue to next step (chain is fault-tolerant)

    async def _run_step(self, step: Step, ctx: dict) -> None:
        logger.debug("[Chains] Step: %s (%s)", step.name, step.type)

        if step.type == "prompt":
            cfg    = step.config
            prompt = _render(cfg["prompt"], ctx)
            result = ""
            gen    = self._router.stream(
                prompt,
                model=cfg.get("model"),
                use_history=cfg.get("use_history", False),
            )
            for chunk in gen:
                result += chunk
            ctx[step.name] = result

        elif step.type == "send":
            if not self._channel:
                logger.warning("[Chains] No channel manager — skipping send step: %s", step.name)
                return
            cfg     = step.config
            text    = _render(cfg["text"], ctx)
            channel = _render(cfg["channel"], ctx)
            chat_id = _render(cfg["chat_id"], ctx)
            from channels.base import OutboundMessage, ChannelKind
            adapter = self._channel._adapter_for(ChannelKind(channel))
            if adapter:
                out = OutboundMessage(chat_id=chat_id, text=text)
                await adapter.send(out)
                ctx[step.name] = "sent"
            else:
                logger.warning("[Chains] Channel %s not connected for step %s", channel, step.name)
                ctx[step.name] = "channel_unavailable"

        elif step.type == "webhook":
            if not self._webhooks:
                logger.warning("[Chains] No webhook server — skipping step: %s", step.name)
                return
            cfg         = step.config
            webhook_ctx = _render_dict(cfg.get("context", {}), ctx)
            result      = await self._webhooks.call_outbound(cfg["webhook"], webhook_ctx)
            ctx[step.name] = result

        elif step.type == "condition":
            expression = step.config.get("expression", "false")
            result     = _eval_expression(expression, ctx)
            ctx[step.name] = result
            branch     = step.then_steps if result else step.else_steps
            if branch:
                await self._run_steps(branch, ctx)

        elif step.type == "wait":
            secs = float(step.config.get("seconds", 1))
            logger.debug("[Chains] Waiting %.1fs at step: %s", secs, step.name)
            await asyncio.sleep(secs)
            ctx[step.name] = "waited"

        elif step.type == "set":
            ctx[step.name] = step.config.get("value", "")

        else:
            logger.warning("[Chains] Unknown step type: %s", step.type)

    # ------------------------------------------------------------------
    # Persistence (chains stored as JSON in vault)
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            data = {}
            for name, chain in self._chains.items():
                data[name] = self._chain_to_dict(chain)
            self._vault.store(self.STORE_KEY, json.dumps(data))
        except Exception as exc:
            logger.warning("[Chains] Save error: %s", exc)

    def _load(self) -> None:
        try:
            raw  = self._vault.retrieve(self.STORE_KEY)
            data = json.loads(raw)
            for name, d in data.items():
                self._chains[name] = self._chain_from_dict(d)
            logger.info("[Chains] Loaded %d chain(s).", len(self._chains))
        except KeyError:
            pass
        except Exception as exc:
            logger.warning("[Chains] Load error: %s", exc)

    @staticmethod
    def _chain_to_dict(chain: Chain) -> dict:
        return asdict(chain)

    @staticmethod
    def _chain_from_dict(d: dict) -> Chain:
        steps = [Step(**s) for s in d.pop("steps", [])]
        chain = Chain(**d, steps=[])
        chain.steps = steps
        return chain

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()
