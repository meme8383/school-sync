"""Gradescope source adapter via gradescopeapi library."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from gradescopeapi.classes.connection import GSConnection

from ..config import Config, CourseMapping
from ..models import Assignment

log = logging.getLogger(__name__)

_CRED_FILE = Path.home() / ".gradescope_session"


def _get_connection() -> GSConnection:
    """Authenticate using saved credentials from gradescope-cli login."""
    if not _CRED_FILE.exists():
        raise RuntimeError(
            "No Gradescope session found. Run: gradescope-cli login"
        )
    data = json.loads(_CRED_FILE.read_text())
    conn = GSConnection()
    conn.login(data["email"], data["password"])
    return conn


def _convert(gs_assignment, course: CourseMapping) -> Assignment | None:
    """Convert a gradescopeapi Assignment to our model, filtering out completed work."""
    status = gs_assignment.submissions_status or ""
    if status and status.lower() not in ("no submission", ""):
        return None
    if gs_assignment.grade:
        return None

    aid = gs_assignment.assignment_id
    return Assignment(
        external_id=f"gs:{course.gradescope_id}:{aid or 'none'}",
        title=gs_assignment.name,
        due=gs_assignment.due_date,
        course=course.course_label,
        source="Gradescope",
        link=f"https://www.gradescope.com/courses/{course.gradescope_id}/assignments/{aid}" if aid else None,
        source_status=status,
    )


def fetch_all(cfg: Config) -> list[Assignment]:
    """Fetch assignments from all configured Gradescope courses."""
    all_assignments: list[Assignment] = []
    conn = None

    for course in cfg.courses:
        if not course.gradescope_id:
            continue
        log.info("Fetching Gradescope assignments for %s (id=%s)", course.course_label, course.gradescope_id)
        try:
            if conn is None:
                conn = _get_connection()
            gs_assignments = conn.account.get_assignments(course.gradescope_id)
            parsed = [a for gs in gs_assignments if (a := _convert(gs, course))]
            log.info("  -> %d actionable assignments", len(parsed))
            all_assignments.extend(parsed)
        except Exception:
            log.exception("Failed to fetch Gradescope for %s", course.course_label)

    return all_assignments
