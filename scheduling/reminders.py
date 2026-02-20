"""
scheduling/reminders.py
-----------------------
Ruby – Smart Reminder System

Parses natural language reminder requests and schedules one-shot or
recurring reminders. The AI model (via ModelRouter) is used to extract
the time/recurrence from free-form text, making it robust against
many phrasings.

Supported phrasings (examples)
-------------------------------
  "Remind me in 30 minutes to check the build"
  "Remind me tomorrow at 9am to send the weekly report"
  "Remind me every Monday at 8am to review PRs"
  "Set a reminder for Friday at 3pm — dentist appointment"
  "Remind me on March 15 at noon to file taxes"

Usage
-----
    from scheduling.reminders import ReminderManager

    rm = ReminderManager(router=router, channel_mgr=mgr)
    reminder = await rm.set_reminder_from_text(
        text="remind me in 2 hours to check the deployment",
        default_chat_id="+1234567890",
        default_channel="telegram",
    )
    print(reminder)  # Reminder(...)
    await rm.run()   # runs forever, checking for due reminders
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("ruby.scheduling.reminders")

STORE_KEY = "reminders"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Reminder:
    id:         str
    text:       str            # what Ruby will say when the reminder fires
    fire_at:    float          # unix timestamp (absolute)
    channel:    str   = ""
    chat_id:    str   = ""
    recurring:  bool  = False
    recur_secs: int   = 0      # interval in seconds for recurring reminders
    fired:      bool  = False
    created_at: float = field(default_factory=time.time)
    raw_input:  str   = ""     # original user text

    def is_due(self) -> bool:
        return not self.fired and time.time() >= self.fire_at

    def human_time(self) -> str:
        return datetime.fromtimestamp(self.fire_at).strftime("%A %b %d at %-I:%M %p")


# ---------------------------------------------------------------------------
# Natural-language time parser (AI-assisted + regex fallback)
# ---------------------------------------------------------------------------

_RELATIVE_PATTERNS = [
    # "in 30 minutes", "in 2 hours", "in 1 hour 30 min"
    (re.compile(r"in\s+(\d+)\s+minute", re.I),  lambda m: timedelta(minutes=int(m.group(1)))),
    (re.compile(r"in\s+(\d+)\s+hour",   re.I),  lambda m: timedelta(hours=int(m.group(1)))),
    (re.compile(r"in\s+(\d+)\s+day",    re.I),  lambda m: timedelta(days=int(m.group(1)))),
    (re.compile(r"in\s+(\d+)\s+week",   re.I),  lambda m: timedelta(weeks=int(m.group(1)))),
    (re.compile(r"in\s+half\s+an?\s+hour", re.I), lambda m: timedelta(minutes=30)),
    (re.compile(r"in\s+an?\s+hour",        re.I), lambda m: timedelta(hours=1)),
    # "tomorrow at 9am"
    (re.compile(r"tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I),
     lambda m: _tomorrow_at(int(m.group(1)), int(m.group(2) or 0), m.group(3))),
    # "today at 3pm"
    (re.compile(r"today\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I),
     lambda m: _today_at(int(m.group(1)), int(m.group(2) or 0), m.group(3))),
]

_RECUR_PATTERNS = [
    (re.compile(r"every\s+(minute|min)",   re.I), 60),
    (re.compile(r"every\s+(hour)",         re.I), 3600),
    (re.compile(r"every\s+(\d+)\s+minute", re.I), None),   # group(1) * 60
    (re.compile(r"every\s+(\d+)\s+hour",   re.I), None),   # group(1) * 3600
    (re.compile(r"every\s+day|daily",      re.I), 86400),
    (re.compile(r"every\s+week|weekly",    re.I), 604800),
]

_WEEKDAYS = {
    "monday":    0, "tuesday":  1, "wednesday": 2,
    "thursday":  3, "friday":   4, "saturday":  5, "sunday":    6,
}
_DAY_RE = re.compile(
    r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?",
    re.I,
)


def _today_at(hour: int, minute: int, ampm: Optional[str]) -> timedelta:
    hour = _to_24h(hour, ampm)
    now  = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target - now


def _tomorrow_at(hour: int, minute: int, ampm: Optional[str]) -> timedelta:
    hour   = _to_24h(hour, ampm)
    now    = datetime.now()
    target = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target - now


def _to_24h(hour: int, ampm: Optional[str]) -> int:
    if ampm:
        if ampm.lower() == "pm" and hour != 12:
            hour += 12
        elif ampm.lower() == "am" and hour == 12:
            hour = 0
    return hour


def _parse_delay_regex(text: str) -> tuple[Optional[timedelta], Optional[int]]:
    """
    Try to extract (delay, recur_secs) from text using regex.
    Returns (None, None) if no match found.
    """
    # Check recurring
    recur_secs: Optional[int] = None
    m = _DAY_RE.search(text)
    if m:
        day_idx = _WEEKDAYS[m.group(1).lower()]
        hour    = int(m.group(2) or 9)
        minute  = int(m.group(3) or 0)
        ampm    = m.group(4)
        hour    = _to_24h(hour, ampm)
        now     = datetime.now()
        days_ahead = (day_idx - now.weekday()) % 7 or 7
        target  = (now + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        delay      = target - now
        recur_secs = 7 * 86400
        return delay, recur_secs

    for pattern, secs in _RECUR_PATTERNS:
        m = pattern.search(text)
        if m:
            if secs is None:
                # "every N minutes/hours"
                val = int(m.group(1))
                unit = m.group(0).lower()
                secs = val * (60 if "minute" in unit else 3600)
            recur_secs = secs
            break

    # Now get the initial delay
    for pattern, delta_fn in _RELATIVE_PATTERNS:
        m = pattern.search(text)
        if m:
            return delta_fn(m), recur_secs

    return None, recur_secs


async def parse_reminder_with_ai(text: str, router) -> Optional[dict]:
    """
    Use the AI model to extract structured reminder info from free-form text.
    Returns dict with keys: delay_seconds, reminder_text, recurring, recur_seconds
    or None if parsing failed.
    """
    now_str = datetime.now().strftime("%A %B %d %Y %H:%M")
    prompt  = f"""Extract reminder information from the user's message. Current time: {now_str}

User message: "{text}"

Reply with ONLY a JSON object (no markdown) with these fields:
  delay_seconds  : int   — how many seconds from now until the reminder fires
  reminder_text  : str   — what to remind the user about (concise)
  recurring      : bool  — true if this repeats
  recur_seconds  : int   — interval in seconds if recurring, else 0

Example: {{"delay_seconds": 1800, "reminder_text": "Check the build", "recurring": false, "recur_seconds": 0}}"""

    try:
        response = router.chat(prompt, use_history=False, temperature=0)
        # Strip markdown fences if present
        clean = re.sub(r"```[a-z]*\n?", "", response).strip().strip("`")
        return json.loads(clean)
    except Exception as exc:
        logger.warning("[Reminders] AI parse failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# ReminderManager
# ---------------------------------------------------------------------------

class ReminderManager:
    """
    Manages one-shot and recurring reminders for Ruby.

    Parameters
    ----------
    router      : ModelRouter      — for AI-assisted time parsing & response generation
    channel_mgr : ChannelManager | None
    vault       : Vault | None
    tick        : int              — check interval in seconds (default: 30)
    """

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
        self._reminders:  dict[str, Reminder] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def set_reminder_from_text(
        self,
        text:            str,
        default_channel: str = "",
        default_chat_id: str = "",
    ) -> Reminder:
        """
        Parse *text* as a natural language reminder request and schedule it.
        Returns the created Reminder.
        """
        # 1. Try regex first (fast, no API call)
        delay, recur_secs = _parse_delay_regex(text)

        # 2. Fall back to AI parsing
        if delay is None:
            parsed = await parse_reminder_with_ai(text, self._router)
            if parsed:
                delay_secs = max(10, int(parsed.get("delay_seconds", 60)))
                delay      = timedelta(seconds=delay_secs)
                if not recur_secs and parsed.get("recurring"):
                    recur_secs = int(parsed.get("recur_seconds", 0))
                # extract reminder message from AI
                reminder_text = parsed.get("reminder_text", text)
            else:
                # Last resort: 60 seconds
                delay         = timedelta(seconds=60)
                reminder_text = text
        else:
            # Extract what to remind about from the text
            reminder_text = _extract_reminder_content(text)

        fire_at   = time.time() + delay.total_seconds()
        recurring = (recur_secs or 0) > 0

        return self.add_reminder(
            text        = reminder_text,
            fire_at     = fire_at,
            channel     = default_channel,
            chat_id     = default_chat_id,
            recurring   = recurring,
            recur_secs  = recur_secs or 0,
            raw_input   = text,
        )

    def add_reminder(
        self,
        text:       str,
        fire_at:    float,
        channel:    str = "",
        chat_id:    str = "",
        recurring:  bool = False,
        recur_secs: int  = 0,
        raw_input:  str  = "",
    ) -> Reminder:
        import secrets
        rid = secrets.token_hex(6)
        r   = Reminder(
            id=rid, text=text, fire_at=fire_at,
            channel=channel, chat_id=chat_id,
            recurring=recurring, recur_secs=recur_secs,
            raw_input=raw_input,
        )
        self._reminders[rid] = r
        self._save()
        logger.info(
            "[Reminders] Set: %r — fires at %s%s",
            text, r.human_time(), " (recurring)" if recurring else ""
        )
        return r

    def cancel(self, reminder_id: str) -> None:
        if reminder_id not in self._reminders:
            raise KeyError(f"No reminder with id: {reminder_id!r}")
        del self._reminders[reminder_id]
        self._save()
        logger.info("[Reminders] Cancelled: %s", reminder_id)

    def list_reminders(self, include_fired: bool = False) -> list[Reminder]:
        return [
            r for r in self._reminders.values()
            if include_fired or not r.fired
        ]

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        logger.info("[Reminders] Manager started. Tick every %ds.", self._tick)
        while True:
            try:
                await self._tick_once()
            except Exception as exc:
                logger.exception("[Reminders] Tick error: %s", exc)
            await asyncio.sleep(self._tick)

    async def _tick_once(self) -> None:
        due = [r for r in self._reminders.values() if r.is_due()]
        for reminder in due:
            asyncio.create_task(self._fire(reminder))

    async def _fire(self, reminder: Reminder) -> None:
        logger.info("[Reminders] Firing: %r", reminder.text)
        message = f"⏰ **Reminder:** {reminder.text}"

        if reminder.channel and reminder.chat_id and self._channel_mgr:
            from channels.base import OutboundMessage, ChannelKind
            try:
                adapter = self._channel_mgr._adapter_for(ChannelKind(reminder.channel))
                if adapter:
                    out = OutboundMessage(chat_id=reminder.chat_id, text=message)
                    await adapter.send(out)
            except Exception as exc:
                logger.exception("[Reminders] Delivery error: %s", exc)
        else:
            logger.info("[Reminders] %s", message)

        if reminder.recurring and reminder.recur_secs > 0:
            reminder.fire_at = time.time() + reminder.recur_secs
        else:
            reminder.fired = True

        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            data = {rid: asdict(r) for rid, r in self._reminders.items()}
            self._vault.store(STORE_KEY, json.dumps(data))
        except Exception as exc:
            logger.warning("[Reminders] Save error: %s", exc)

    def _load(self) -> None:
        try:
            raw  = self._vault.retrieve(STORE_KEY)
            data = json.loads(raw)
            for rid, d in data.items():
                self._reminders[rid] = Reminder(**d)
            active = sum(1 for r in self._reminders.values() if not r.fired)
            logger.info("[Reminders] Loaded %d active reminder(s).", active)
        except KeyError:
            pass
        except Exception as exc:
            logger.warning("[Reminders] Load error: %s", exc)

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()


# ---------------------------------------------------------------------------
# Helper: extract reminder content from text
# ---------------------------------------------------------------------------

_STRIP_PATTERNS = [
    re.compile(r"remind\s+me\s+(in|at|on|every|tomorrow|today).*?to\s+", re.I),
    re.compile(r"set\s+a\s+reminder\s+.*?(?:to|—|-)\s+", re.I),
    re.compile(r"remind\s+me\s+to\s+", re.I),
]

def _extract_reminder_content(text: str) -> str:
    """Best-effort extraction of the 'what to remind about' from raw text."""
    for pat in _STRIP_PATTERNS:
        m = pat.search(text)
        if m:
            return text[m.end():].strip()
    return text.strip()
