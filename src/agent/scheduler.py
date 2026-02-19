"""Background task scheduler for the agent."""

import asyncio
import time
import logging
from typing import Callable, Coroutine, NamedTuple, Any

logger = logging.getLogger(__name__)


class Job(NamedTuple):
    """A scheduled job."""
    task: str
    interval: int  # Seconds
    last_run: float
    func: Callable[..., Coroutine[Any, Any, None]] = None # Optional direct function callback


class Scheduler:
    """Manages periodic background tasks."""

    def __init__(self):
        self._jobs: list[Job] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def add_job(self, task: str, interval: int) -> None:
        """Add a job to be executed periodically by the agent.
        
        Args:
            task: The instruction string to send to the agent (e.g., "Check email")
            interval: How often to run in seconds
        """
        job = Job(task=task, interval=interval, last_run=time.time())
        self._jobs.append(job)
        logger.info(f"Added background job: '{task}' every {interval}s")

    async def start(self, agent_callback: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        """Start the scheduler loop in the background.
        
        Args:
            agent_callback: Async function to call with the task instruction.
        """
        if self._running:
            return

        self._running = True
        logger.info("Scheduler starting...")
        self._task = asyncio.create_task(self._run_loop(agent_callback))

    async def _run_loop(self, agent_callback: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        """Internal execution loop."""
        logger.info("Scheduler loop started.")
        try:
            while self._running:
                now = time.time()
                for i, job in enumerate(self._jobs):
                    if now - job.last_run >= job.interval:
                        logger.info(f"Triggering job: {job.task}")
                        
                        # Update last run FIRST to avoid double triggers if task is slow
                        self._jobs[i] = job._replace(last_run=now)
                        
                        try:
                            # Execute the task
                            asyncio.create_task(agent_callback(job.task))
                        except Exception as e:
                            logger.error(f"Job trigger error: {e}")
                
                # Check every second
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled.")
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            self._running = False

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped.")
