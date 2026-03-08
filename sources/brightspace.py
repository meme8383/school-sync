"""Brightspace source adapter via gws calendar events."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import Config, CourseMapping
from ..models import Assignment

log = logging.getLogger(__name__)


def _gws_calendar_events(calendar_id: str, time_min: str, time_max: str) -> list[dict]:
    """Call gws calendar events list and return items."""
    params = json.dumps({
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
    })
    result = subprocess.run(
        ["gws", "calendar", "events", "list", "--params", params],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        log.error("gws calendar failed (rc=%d): %s", result.returncode, result.stderr)
        raise RuntimeError(f"gws calendar exited {result.returncode}")

    data = json.loads(result.stdout)
    return data.get("items", data.get("events", []))


def _is_availability(summary: str) -> bool:
    """Filter out availability windows, not actual assignments."""
    s = (summary or "").strip()
    if s.endswith(" - Available"):
        return True
    if re.search(r"\bAvailability\s*Ends\b", s, flags=re.I):
        return True
    if re.search(r"\bAvailable\b", s, flags=re.I) and not s.endswith(" - Due"):
        return True
    return False


def _normalize_title(summary: str) -> str:
    s = (summary or "").strip()
    if s.endswith(" - Due"):
        s = s[:-6]
    return s.strip()


def _extract_brightspace_key(description: str) -> str | None:
    """Extract bs:<ou>:<event_id> from the event description URL."""
    if not description:
        return None
    m = re.search(r"/d2l/le/calendar/(\d+)/event/(\d+)/", description)
    if not m:
        return None
    return f"bs:{m.group(1)}:{m.group(2)}"


def _extract_ou(description: str) -> str | None:
    if not description:
        return None
    m = re.search(r"\bou=(\d+)\b", description)
    if m:
        return m.group(1)
    # Also try from the calendar URL pattern
    m = re.search(r"/d2l/le/calendar/(\d+)/", description)
    return m.group(1) if m else None


def _parse_dt(event: dict, field: str) -> datetime | None:
    """Parse a Google Calendar event start/end datetime."""
    obj = event.get(field, {})
    if "dateTime" in obj:
        return datetime.fromisoformat(obj["dateTime"])
    if "date" in obj:
        return datetime.strptime(obj["date"], "%Y-%m-%d").replace(
            hour=23, minute=59
        )
    return None


def fetch_all(cfg: Config) -> list[Assignment]:
    """Fetch Brightspace assignments via gws calendar."""
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz)
    time_min = now.strftime("%Y-%m-%dT00:00:00Z")
    time_max = (now + timedelta(days=cfg.sync_days_ahead)).strftime("%Y-%m-%dT00:00:00Z")

    # Build OU -> course mapping
    ou_map: dict[str, CourseMapping] = {}
    for c in cfg.courses:
        if c.brightspace_ou:
            ou_map[c.brightspace_ou] = c

    log.info("Fetching Brightspace calendar events from gws (%s)", cfg.brightspace_calendar_id)
    try:
        events = _gws_calendar_events(cfg.brightspace_calendar_id, time_min, time_max)
    except Exception:
        log.exception("Failed to fetch Brightspace calendar")
        return []

    assignments: list[Assignment] = []
    for ev in events:
        summary = ev.get("summary", "")
        description = ev.get("description", "")

        if _is_availability(summary):
            continue

        ou = _extract_ou(description)

        bs_key = _extract_brightspace_key(description)
        if not bs_key:
            # Fall back to event ID-based key
            event_id = ev.get("id", "")
            if ou:
                bs_key = f"bs:{ou}:{event_id}"
            else:
                bs_key = f"bs:unknown:{event_id}"

        course_map = ou_map.get(ou, None) if ou else None
        course_label = course_map.course_label if course_map else "Unknown"

        due = _parse_dt(ev, "start") or _parse_dt(ev, "end")
        if due and due.tzinfo is None:
            due = due.replace(tzinfo=tz)

        title = _normalize_title(summary)

        # Build a Brightspace link from the description if possible
        link = None
        link_m = re.search(r"(https://purdue\.brightspace\.com/[^\s<\"]+)", description)
        if link_m:
            link = link_m.group(1)

        assignments.append(Assignment(
            external_id=bs_key,
            title=title,
            due=due,
            course=course_label,
            source="Brightspace",
            link=link,
            source_status=None,
        ))

    log.info("  -> %d Brightspace assignments after filtering", len(assignments))
    return assignments
