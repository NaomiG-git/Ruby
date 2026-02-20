"""
scheduling/run_job.py
---------------------
Entry point for running a single Ruby cron job from the command line.

Windows Task Scheduler calls:
    pythonw.exe -m scheduling.run_job "<job_name>"

This module:
  1. Loads the job from the vault
  2. Initialises the ModelRouter (re-uses stored OAuth tokens)
  3. Runs the job prompt and delivers output via the configured channel
  4. Exits cleanly

Not intended for direct user use.
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ruby.scheduling.run_job")


async def _main(job_name: str) -> None:
    from security.vault  import Vault
    from models.router   import ModelRouter
    from scheduling.cron import CronScheduler

    vault     = Vault()
    router    = ModelRouter(vault=vault)
    scheduler = CronScheduler(router=router, vault=vault)

    try:
        job = scheduler.get_job(job_name)
    except KeyError:
        logger.error("No cron job named %r found in vault.", job_name)
        sys.exit(1)

    if not job.enabled:
        logger.info("Job %r is disabled — exiting.", job_name)
        sys.exit(0)

    logger.info("Running job: %s", job_name)
    response = ""
    try:
        gen = router.stream(job.prompt, use_history=False)
        for chunk in gen:
            response += chunk
    except Exception as exc:
        logger.exception("Router error: %s", exc)
        sys.exit(2)

    # Deliver via channel if configured
    if job.channel and job.chat_id:
        try:
            from channels.manager import ChannelManager
            from channels.base    import OutboundMessage, ChannelKind
            # We can't run the full channel stack here — just use the
            # adapter directly for the delivery
            from channels.manager import _load_adapters, _ADAPTER_REGISTRY
            _load_adapters()
            cls     = _ADAPTER_REGISTRY.get(job.channel)
            if cls:
                adapter = cls(config={}, vault=vault)
                await adapter.connect()
                out = OutboundMessage(chat_id=job.chat_id, text=response)
                await adapter.send(out)
                await adapter.disconnect()
            else:
                logger.warning("Unknown channel: %s", job.channel)
        except Exception as exc:
            logger.exception("Delivery error: %s", exc)

    job.mark_run()
    if job.one_shot:
        scheduler.remove_job(job_name)
    else:
        scheduler._save()

    logger.info("Job %s complete.", job_name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scheduling.run_job <job_name>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
