"""Gradescope source adapter via gradescope-cli."""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import Config, CourseMapping
from ..models import Assignment

log = logging.getLogger(__name__)


def _run_cli(course_id: str) -> str:
    """Run gradescope-cli assignments <course_id> and return stdout."""
    result = subprocess.run(
        ["bash", "-lc", f"gradescope-cli assignments {course_id}"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        log.error("gradescope-cli failed (rc=%d): %s", result.returncode, result.stderr)
        raise RuntimeError(f"gradescope-cli exited {result.returncode}")
    return result.stdout


def _parse_assignments(raw: str, course: CourseMapping, tz: ZoneInfo) -> list[Assignment]:
    """Parse gradescope-cli text output into Assignment objects."""
    assignments: list[Assignment] = []
    current_id: str | None = None
    current_title: str | None = None
    current_due: datetime | None = None
    current_status: str | None = None
    current_grade: str | None = None

    for line in raw.splitlines():
        # Assignment header: [id] title
        m = re.match(r"^\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+)$", line)
        if m:
            # Flush previous
            if current_title is not None:
                a = _make_assignment(
                    current_id, current_title, current_due,
                    current_status, current_grade, course,
                )
                if a:
                    assignments.append(a)
            current_id = m.group("id").strip()
            if current_id.lower() == "none":
                current_id = None
            current_title = m.group("title").strip()
            current_due = None
            current_status = None
            current_grade = None
            continue

        # Metadata lines
        dm = re.search(r"Due:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", line)
        if dm:
            current_due = datetime.strptime(dm.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        sm = re.search(r"Status:\s*(.+)$", line)
        if sm:
            current_status = sm.group(1).strip()

        gm = re.search(r"Grade:\s*(.+)$", line)
        if gm:
            current_grade = gm.group(1).strip()

    # Flush last
    if current_title is not None:
        a = _make_assignment(
            current_id, current_title, current_due,
            current_status, current_grade, course,
        )
        if a:
            assignments.append(a)

    return assignments


def _make_assignment(
    aid: str | None,
    title: str,
    due: datetime | None,
    status: str | None,
    grade: str | None,
    course: CourseMapping,
) -> Assignment | None:
    # Only sync assignments that haven't been submitted/graded
    if status and status.lower() not in ("no submission", ""):
        return None
    if grade:
        return None

    eid = f"gs:{course.gradescope_id}:{aid or 'none'}"
    return Assignment(
        external_id=eid,
        title=title,
        due=due,
        course=course.course_label,
        source="Gradescope",
        link=f"https://www.gradescope.com/courses/{course.gradescope_id}/assignments/{aid}" if aid else None,
        source_status=status,
    )


def fetch_all(cfg: Config) -> list[Assignment]:
    """Fetch assignments from all configured Gradescope courses."""
    tz = ZoneInfo(cfg.timezone)
    all_assignments: list[Assignment] = []

    for course in cfg.courses:
        if not course.gradescope_id:
            continue
        log.info("Fetching Gradescope assignments for %s (id=%s)", course.course_label, course.gradescope_id)
        try:
            raw = _run_cli(course.gradescope_id)
            parsed = _parse_assignments(raw, course, tz)
            log.info("  -> %d actionable assignments", len(parsed))
            all_assignments.extend(parsed)
        except Exception:
            log.exception("Failed to fetch Gradescope for %s", course.course_label)

    return all_assignments
