"""
scheduling/manager.py
---------------------
Ruby – Scheduling Manager

Central coordinator that owns and runs all scheduling subsystems:
  - CronScheduler      (recurring cron jobs)
  - ReminderManager    (natural-language smart reminders)
  - WebhookServer      (inbound + outbound webhook triggers)
  - ChainRunner        (multi-step automation chains)
  - WindowsTaskScheduler (optional Windows Task Scheduler sync)

Usage
-----
    import asyncio
    from models.router       import ModelRouter
    from channels.manager    import ChannelManager
    from scheduling.manager  import SchedulingManager

    router  = ModelRouter()
    router.authenticate_all()

    channel_mgr = ChannelManager(router=router)
    channel_mgr.add_channel("telegram", {})

    sched = SchedulingManager(router=router, channel_mgr=channel_mgr)

    # Add a cron job
    sched.cron.add_job(
        name="morning_brief",
        cron="0 8 * * *",
        prompt="Give me a brief morning summary.",
        channel="telegram",
        chat_id="123456789",
    )

    # Add a reminder from natural language
    asyncio.run(sched.reminders.set_reminder_from_text(
        "Remind me in 30 minutes to review the PR",
        default_channel="telegram",
        default_chat_id="123456789",
    ))

    # Register a webhook
    sched.webhooks.register_inbound(
        name="github_push",
        prompt="GitHub push to {{repository.name}}: {{commits}}. Summarise.",
        channel="telegram",
        chat_id="123456789",
    )

    # Run everything
    asyncio.run(sched.run())
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from .cron         import CronScheduler
from .reminders    import ReminderManager
from .webhooks     import WebhookServer
from .chains       import ChainRunner
from .windows_tasks import WindowsTaskScheduler

logger = logging.getLogger("ruby.scheduling.manager")


class SchedulingManager:
    """
    Owns all scheduling subsystems and runs them concurrently.

    Parameters
    ----------
    router          : ModelRouter
    channel_mgr     : ChannelManager | None
    vault           : Vault | None
    webhook_port    : int    — inbound webhook server port (default: 8888)
    cron_tick       : int    — cron check interval seconds (default: 30)
    reminder_tick   : int    — reminder check interval seconds (default: 30)
    sync_win_tasks  : bool   — sync cron jobs to Windows Task Scheduler (default: True on Windows)
    """

    def __init__(
        self,
        router,
        channel_mgr=None,
        vault=None,
        webhook_port:   int  = 8888,
        cron_tick:      int  = 30,
        reminder_tick:  int  = 30,
        sync_win_tasks: bool = True,
    ):
        self._router      = router
        self._channel_mgr = channel_mgr
        self._vault       = vault or self._default_vault()

        self.cron     = CronScheduler(
            router=self._router,
            channel_mgr=self._channel_mgr,
            vault=self._vault,
            tick=cron_tick,
        )
        self.reminders = ReminderManager(
            router=self._router,
            channel_mgr=self._channel_mgr,
            vault=self._vault,
            tick=reminder_tick,
        )
        self.webhooks = WebhookServer(
            router=self._router,
            channel_mgr=self._channel_mgr,
            vault=self._vault,
            port=webhook_port,
        )
        self.chains = ChainRunner(
            router=self._router,
            channel_mgr=self._channel_mgr,
            webhook_server=self.webhooks,
            vault=self._vault,
        )

        # Windows Task Scheduler (Windows-only)
        self.win_tasks: Optional[WindowsTaskScheduler] = None
        if sync_win_tasks and sys.platform == "win32":
            self.win_tasks = WindowsTaskScheduler()
            self.win_tasks.sync_all(self.cron)
            logger.info("[Scheduling] Windows Task Scheduler sync complete.")

    # ------------------------------------------------------------------
    # Run all subsystems concurrently
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start all scheduling subsystems and run until cancelled."""
        logger.info("[Scheduling] Starting all scheduling subsystems...")

        tasks = [
            asyncio.create_task(self.cron.run(),      name="cron"),
            asyncio.create_task(self.reminders.run(), name="reminders"),
            asyncio.create_task(self.webhooks.run(),  name="webhooks"),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()

    # ------------------------------------------------------------------
    # Convenience: parse and schedule a reminder from natural language
    # ------------------------------------------------------------------

    async def remind(
        self,
        text:    str,
        channel: str = "",
        chat_id: str = "",
    ):
        """Shorthand for ReminderManager.set_reminder_from_text()."""
        return await self.reminders.set_reminder_from_text(
            text=text,
            default_channel=channel,
            default_chat_id=chat_id,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "cron_jobs":           len(self.cron.list_jobs()),
            "active_reminders":    len(self.reminders.list_reminders()),
            "inbound_webhooks":    len(self.webhooks._inbound),
            "outbound_webhooks":   len(self.webhooks._outbound),
            "stored_chains":       len(self.chains.list_chains()),
            "win_tasks_synced":    self.win_tasks is not None,
        }

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()
