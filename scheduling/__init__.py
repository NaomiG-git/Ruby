"""
scheduling/__init__.py
----------------------
Ruby – Scheduling & Automation

Public API
----------
    from scheduling import (
        SchedulingManager,
        CronScheduler,
        ReminderManager,
        WebhookServer,
        ChainRunner,
        ChainBuilder,
        WindowsTaskScheduler,
    )

Quick-start
-----------
    from models.router    import ModelRouter
    from channels.manager import ChannelManager
    from scheduling       import SchedulingManager

    router      = ModelRouter()
    channel_mgr = ChannelManager(router=router)

    sched = SchedulingManager(router=router, channel_mgr=channel_mgr)

    # Cron job: run a prompt every morning at 08:00
    sched.cron.add_job(
        name="morning_brief",
        cron="0 8 * * *",
        prompt="Give me today's briefing.",
        channel="telegram",
        chat_id="123456789",
    )

    asyncio.run(sched.run())

Vault storage keys
------------------
    cron_jobs          → list[CronJob]
    reminders          → list[Reminder]
    webhook_inbound    → list[InboundWebhook]
    webhook_outbound   → list[OutboundWebhook]
    chains             → dict[str, Chain]
"""

from .manager      import SchedulingManager
from .cron         import CronScheduler, CronJob
from .reminders    import ReminderManager, Reminder
from .webhooks     import WebhookServer, InboundWebhook, OutboundWebhook
from .chains       import ChainRunner, ChainBuilder, Chain, ChainStep
from .windows_tasks import WindowsTaskScheduler

__all__ = [
    "SchedulingManager",
    "CronScheduler",
    "CronJob",
    "ReminderManager",
    "Reminder",
    "WebhookServer",
    "InboundWebhook",
    "OutboundWebhook",
    "ChainRunner",
    "ChainBuilder",
    "Chain",
    "ChainStep",
    "WindowsTaskScheduler",
]
