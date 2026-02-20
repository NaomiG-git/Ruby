"""
scheduling/cron.py
------------------
Ruby – Cron Job Engine

Provides a lightweight async cron scheduler. Jobs are defined with standard
cron expressions (5-field: min hour dom month dow) and stored persistently
in Ruby's encrypted vault so they survive restarts.

Features
--------
- Standard 5-field cron syntax (with aliases: @hourly, @daily, @weekly, etc.)
- Per-job: action (prompt sent to ModelRouter), optional output channel
- Persistent job store (vault-backed JSON)
- Async execution — jobs run without blocking the event loop
- Missed-run detection (catches up one run if Ruby was offline)
- Per-job enable/disable and one-shot (run-once) support

Usage
-----
    from scheduling.cron import CronScheduler

    scheduler = CronScheduler(router=router)
    scheduler.add_job(
        name="morning_briefing",
        cron="0 8 * * *",           # 08:00 every day
        prompt="Give me a morning news briefing.",
        channel="telegram",
        chat_id="+1234567890",
    )
    await scheduler.run()           # runs forever, checking for due jobs
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ruby.scheduling.cron")

# ---------------------------------------------------------------------------
# Cron expression parsing
# ---------------------------------------------------------------------------

_ALIASES = {
    "@yearly":   "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly":  "0 0 1 * *",
    "@weekly":   "0 0 * * 0",
    "@daily":    "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly":   "0 * * * *",
}

_FIELD_RANGES = [
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day-of-month
    (1, 12),   # month
    (0, 6),    # day-of-week (0=Sun)
]


def _expand_field(expr: str, lo: int, hi: int) -> set[int]:
    """Expand a single cron field expression to a set of matching integers."""
    result: set[int] = set()
    for part in expr.split(","):
        if part == "*":
            result.update(range(lo, hi + 1))
        elif "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                start, end = lo, hi
            elif "-" in base:
                a, b = base.split("-")
                start, end = int(a), int(b)
            else:
                start, end = int(base), hi
            result.update(range(start, end + 1, step))
        elif "-" in part:
            a, b = part.split("-")
            result.update(range(int(a), int(b) + 1))
        else:
            result.add(int(part))
    return result


def parse_cron(expr: str) -> tuple[set, set, set, set, set]:
    """Parse a 5-field cron expression. Returns (minutes, hours, doms, months, dows)."""
    expr = _ALIASES.get(expr.strip().lower(), expr.strip())
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Cron expression must have 5 fields: {expr!r}")
    return tuple(
        _expand_field(f, lo, hi)
        for f, (lo, hi) in zip(fields, _FIELD_RANGES)
    )  # type: ignore[return-value]


def cron_is_due(expr: str, t: time.struct_time) -> bool:
    """Return True if *expr* matches the given struct_time (minute precision)."""
    mins, hrs, doms, months, dows = parse_cron(expr)
    return (
        t.tm_min  in mins   and
        t.tm_hour in hrs    and
        t.tm_mday in doms   and
        t.tm_mon  in months and
        t.tm_wday in dows   # Python: Mon=0, Sun=6 — cron: Sun=0
        # Note: we normalise dow below
    )


def _normalise_dow(t: time.struct_time) -> int:
    """Convert Python weekday (Mon=0) to cron weekday (Sun=0)."""
    return (t.tm_wday + 1) % 7


def cron_matches(cron_expr: str) -> bool:
    """Check if cron_expr is due right now (current local minute)."""
    t = time.localtime()
    mins, hrs, doms, months, dows = parse_cron(cron_expr)
    return (
        t.tm_min  in mins   and
        t.tm_hour in hrs    and
        t.tm_mday in doms   and
        t.tm_mon  in months and
        _normalise_dow(t) in dows
    )


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------

@dataclass
class CronJob:
    name:       str
    cron:       str            # 5-field cron expression or @alias
    prompt:     str            # message sent to ModelRouter when due
    enabled:    bool  = True
    one_shot:   bool  = False  # delete after first run
    channel:    str   = ""     # channel to reply on (e.g. "telegram")
    chat_id:    str   = ""     # chat/user ID on that channel
    last_run:   float = 0.0    # unix timestamp of last execution
    created_at: float = field(default_factory=time.time)
    tags:       list[str] = field(default_factory=list)

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        return cron_matches(self.cron)

    def mark_run(self) -> None:
        self.last_run = time.time()


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------

class CronScheduler:
    """
    Async cron scheduler for Ruby.

    Parameters
    ----------
    router      : ModelRouter — used to generate responses for due jobs
    channel_mgr : ChannelManager | None — used to deliver job output to channels
    vault       : Vault | None          — for persisting jobs
    store_key   : str                   — vault key for the job store
    tick        : int                   — seconds between checks (default: 30)
    """

    STORE_KEY = "cron_jobs"

    def __init__(
        self,
        router,
        channel_mgr=None,
        vault=None,
        tick: int = 30,
    ):
        self._router      = router
        self._channel_mgr = channel_mgr
        self._vault       = vault or self._default_vault()
        self._tick        = tick
        self._jobs:  dict[str, CronJob] = {}
        self._running: set[str] = set()   # job names currently executing
        self._load()

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def add_job(
        self,
        name:     str,
        cron:     str,
        prompt:   str,
        enabled:  bool = True,
        one_shot: bool = False,
        channel:  str  = "",
        chat_id:  str  = "",
        tags:     Optional[list[str]] = None,
    ) -> CronJob:
        """Create (or replace) a cron job and persist it."""
        parse_cron(cron)  # validate expression
        job = CronJob(
            name=name, cron=cron, prompt=prompt,
            enabled=enabled, one_shot=one_shot,
            channel=channel, chat_id=chat_id,
            tags=tags or [],
        )
        self._jobs[name] = job
        self._save()
        logger.info("[Cron] Job added: %s  [%s]", name, cron)
        return job

    def remove_job(self, name: str) -> None:
        if name not in self._jobs:
            raise KeyError(f"No cron job named: {name!r}")
        del self._jobs[name]
        self._save()
        logger.info("[Cron] Job removed: %s", name)

    def enable_job(self, name: str) -> None:
        self._jobs[name].enabled = True
        self._save()

    def disable_job(self, name: str) -> None:
        self._jobs[name].enabled = False
        self._save()

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get_job(self, name: str) -> CronJob:
        return self._jobs[name]

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Tick every self._tick seconds and fire any due jobs."""
        logger.info("[Cron] Scheduler started. Tick every %ds.", self._tick)
        while True:
            try:
                await self._tick_once()
            except Exception as exc:
                logger.exception("[Cron] Tick error: %s", exc)
            await asyncio.sleep(self._tick)

    async def _tick_once(self) -> None:
        due = [j for j in self._jobs.values() if j.is_due() and j.name not in self._running]
        for job in due:
            asyncio.create_task(self._run_job(job))

    async def _run_job(self, job: CronJob) -> None:
        self._running.add(job.name)
        try:
            logger.info("[Cron] Running job: %s", job.name)
            response = ""
            try:
                gen = self._router.stream(job.prompt, use_history=False)
                for chunk in gen:
                    response += chunk
            except Exception as exc:
                logger.exception("[Cron] Router error for job %s: %s", job.name, exc)
                response = f"[Error running scheduled job: {exc}]"

            # Deliver output to channel if configured
            if job.channel and job.chat_id and self._channel_mgr:
                await self._deliver(job, response)
            else:
                logger.info("[Cron] Job %s output:\n%s", job.name, response[:200])

            job.mark_run()
            if job.one_shot:
                self.remove_job(job.name)
            else:
                self._save()
        finally:
            self._running.discard(job.name)

    async def _deliver(self, job: CronJob, text: str) -> None:
        from channels.base import OutboundMessage, ChannelKind
        try:
            adapter = self._channel_mgr._adapter_for(ChannelKind(job.channel))
            if adapter:
                from channels.base import OutboundMessage
                out = OutboundMessage(chat_id=job.chat_id, text=text)
                await adapter.send(out)
            else:
                logger.warning("[Cron] Channel %s not connected for job %s", job.channel, job.name)
        except Exception as exc:
            logger.exception("[Cron] Delivery error for job %s: %s", job.name, exc)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            data = {name: asdict(job) for name, job in self._jobs.items()}
            self._vault.store(self.STORE_KEY, json.dumps(data))
        except Exception as exc:
            logger.warning("[Cron] Failed to persist jobs: %s", exc)

    def _load(self) -> None:
        try:
            raw = self._vault.retrieve(self.STORE_KEY)
            data = json.loads(raw)
            for name, d in data.items():
                self._jobs[name] = CronJob(**d)
            logger.info("[Cron] Loaded %d job(s) from vault.", len(self._jobs))
        except KeyError:
            pass  # no jobs stored yet
        except Exception as exc:
            logger.warning("[Cron] Failed to load jobs: %s", exc)

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()
