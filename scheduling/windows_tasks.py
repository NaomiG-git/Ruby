"""
scheduling/windows_tasks.py
---------------------------
Ruby – Windows Task Scheduler Integration

Registers Ruby cron jobs as Windows Task Scheduler tasks so they fire even
when the Ruby UI is closed. Uses the `schtasks.exe` command-line tool (built
into all Windows versions) — no third-party packages needed.

How it works
------------
Each CronJob can be synced to Task Scheduler. When triggered by Windows, the
task runs `pythonw.exe -m scheduling.run_job <job_name>`, which loads the job
from the vault and executes it. Ruby's main process picks up the result.

Requirements
------------
- Windows only (no-op on other platforms)
- Ruby must be run at least once as admin to register tasks under SYSTEM,
  or tasks are registered for the current user (recommended default)

Usage
-----
    from scheduling.windows_tasks import WindowsTaskScheduler

    scheduler = WindowsTaskScheduler()
    scheduler.register_job(job)      # register a CronJob with Task Scheduler
    scheduler.unregister_job(job)    # remove a task
    scheduler.list_ruby_tasks()      # list all Ruby tasks in Task Scheduler
    scheduler.sync_all(cron_scheduler)  # sync all CronJobs → Task Scheduler
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .cron import CronJob, CronScheduler

logger = logging.getLogger("ruby.scheduling.windows_tasks")

_IS_WINDOWS = sys.platform == "win32"
_TASK_PREFIX = "Ruby\\"   # tasks are created under a "Ruby" folder in Task Scheduler


# ---------------------------------------------------------------------------
# Cron → schtasks translation
# ---------------------------------------------------------------------------

def _cron_to_schtasks(cron: str) -> Optional[dict]:
    """
    Translate a 5-field cron expression to schtasks.exe parameters.
    Returns a dict of /SC, /MO, /D, /ST args, or None if not translatable.

    schtasks supports: MINUTE, HOURLY, DAILY, WEEKLY, MONTHLY, ONCE
    Not all cron expressions map cleanly — complex ones return None
    (and those jobs are handled by Ruby's in-process scheduler instead).
    """
    from .cron import parse_cron, _ALIASES
    expr = _ALIASES.get(cron.strip().lower(), cron.strip())
    fields = expr.split()
    if len(fields) != 5:
        return None

    minute_f, hour_f, dom_f, month_f, dow_f = fields

    # @hourly  → "0 * * * *"
    if hour_f == "*" and dom_f == "*" and month_f == "*" and dow_f == "*":
        interval = int(minute_f.lstrip("*/")) if "/" in minute_f else None
        if minute_f == "0":
            return {"SC": "HOURLY"}
        if interval:
            return {"SC": "MINUTE", "MO": str(interval)}
        return None  # complex minute pattern

    # @daily → "0 8 * * *"
    if dom_f == "*" and month_f == "*" and dow_f == "*":
        try:
            h = int(hour_f)
            m = int(minute_f)
            st = f"{h:02d}:{m:02d}"
            return {"SC": "DAILY", "ST": st}
        except ValueError:
            return None

    # Weekly → "0 8 * * 1"
    if dom_f == "*" and month_f == "*" and dow_f not in ("*",):
        try:
            h = int(hour_f)
            m_val = int(minute_f)
            st  = f"{h:02d}:{m_val:02d}"
            day_map = {
                "0": "SUN", "1": "MON", "2": "TUE", "3": "WED",
                "4": "THU", "5": "FRI", "6": "SAT",
            }
            day = day_map.get(dow_f)
            if day:
                return {"SC": "WEEKLY", "D": day, "ST": st}
        except ValueError:
            pass
        return None

    # Monthly → "0 9 1 * *"
    if month_f == "*" and dow_f == "*":
        try:
            h   = int(hour_f)
            mn  = int(minute_f)
            dom = int(dom_f)
            st  = f"{h:02d}:{mn:02d}"
            return {"SC": "MONTHLY", "D": str(dom), "ST": st}
        except ValueError:
            return None

    return None   # too complex for schtasks — use in-process scheduler


# ---------------------------------------------------------------------------
# WindowsTaskScheduler
# ---------------------------------------------------------------------------

class WindowsTaskScheduler:
    """
    Registers/unregisters Ruby cron jobs with Windows Task Scheduler.

    On non-Windows platforms all methods are no-ops that log a warning.

    Parameters
    ----------
    python_exe   : str | None — path to pythonw.exe (defaults to sys.executable)
    run_as_user  : str | None — Windows user to run tasks as (default: current user)
    task_prefix  : str        — subfolder in Task Scheduler (default: "Ruby\\")
    """

    def __init__(
        self,
        python_exe:   Optional[str] = None,
        run_as_user:  Optional[str] = None,
        task_prefix:  str = _TASK_PREFIX,
    ):
        self._python  = python_exe or sys.executable.replace("python.exe", "pythonw.exe")
        self._user    = run_as_user or self._current_user()
        self._prefix  = task_prefix

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_job(self, job: "CronJob") -> bool:
        """
        Register *job* as a Windows Task Scheduler task.
        Returns True if successfully registered, False if skipped / unsupported.
        """
        if not _IS_WINDOWS:
            logger.debug("[WinTasks] Not Windows — skipping register: %s", job.name)
            return False

        args = _cron_to_schtasks(job.cron)
        if args is None:
            logger.info(
                "[WinTasks] Job %r has a complex cron expression (%s); "
                "it will be handled by Ruby's in-process scheduler.",
                job.name, job.cron
            )
            return False

        task_name = f"{self._prefix}{job.name}"
        action    = f'"{self._python}" -m scheduling.run_job "{job.name}"'

        cmd = ["schtasks", "/Create", "/F",
               "/TN", task_name,
               "/TR", action,
               "/SC", args["SC"],
               "/RU", self._user,
               ]
        if "MO" in args:
            cmd += ["/MO", args["MO"]]
        if "D" in args:
            cmd += ["/D", args["D"]]
        if "ST" in args:
            cmd += ["/ST", args["ST"]]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                logger.info("[WinTasks] Registered task: %s", task_name)
                return True
            else:
                logger.error("[WinTasks] schtasks error: %s", result.stderr.strip())
                return False
        except Exception as exc:
            logger.exception("[WinTasks] Failed to register task %s: %s", task_name, exc)
            return False

    def unregister_job(self, job_name: str) -> bool:
        """Remove the Windows Task Scheduler task for *job_name*."""
        if not _IS_WINDOWS:
            return False
        task_name = f"{self._prefix}{job_name}"
        try:
            result = subprocess.run(
                ["schtasks", "/Delete", "/F", "/TN", task_name],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                logger.info("[WinTasks] Removed task: %s", task_name)
                return True
            else:
                logger.warning("[WinTasks] Could not remove task %s: %s", task_name, result.stderr.strip())
                return False
        except Exception as exc:
            logger.exception("[WinTasks] Failed to remove task: %s", exc)
            return False

    def list_ruby_tasks(self) -> list[dict]:
        """Return all Task Scheduler tasks under the Ruby prefix."""
        if not _IS_WINDOWS:
            return []
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/FO", "CSV", "/V", "/TN", self._prefix],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return []
            tasks = []
            lines = result.stdout.strip().splitlines()
            if len(lines) < 2:
                return []
            headers = [h.strip('"') for h in lines[0].split('","')]
            for line in lines[1:]:
                values = [v.strip('"') for v in line.split('","')]
                if len(values) == len(headers):
                    tasks.append(dict(zip(headers, values)))
            return tasks
        except Exception as exc:
            logger.exception("[WinTasks] list error: %s", exc)
            return []

    def sync_all(self, cron_scheduler: "CronScheduler") -> None:
        """
        Ensure all enabled jobs in *cron_scheduler* are registered with
        Task Scheduler, and remove any tasks whose jobs no longer exist.
        """
        if not _IS_WINDOWS:
            return

        current_tasks = {t.get("TaskName", "").split("\\")[-1] for t in self.list_ruby_tasks()}
        job_names     = {j.name for j in cron_scheduler.list_jobs() if j.enabled}

        # Register new/updated jobs
        for job in cron_scheduler.list_jobs():
            if job.enabled:
                self.register_job(job)

        # Remove stale tasks
        for task_name in current_tasks - job_names:
            self.unregister_job(task_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_user() -> str:
        if not _IS_WINDOWS:
            return ""
        import os
        return os.environ.get("USERNAME", "")
