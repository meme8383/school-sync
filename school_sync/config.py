"""Environment-based configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from the package directory (no dependencies)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _read_file_or_env(env_key: str, file_path: str | None = None) -> str:
    """Read from env var first, fall back to file."""
    val = os.environ.get(env_key, "").strip()
    if val:
        return val
    if file_path and Path(file_path).is_file():
        return Path(file_path).read_text().strip()
    return ""


@dataclass
class CourseMapping:
    course_label: str           # e.g. "ECE 50863"
    brightspace_ou: str | None  # e.g. "1489291"
    gradescope_id: str | None   # e.g. "1222491"


@dataclass
class Config:
    # Notion
    notion_api_key: str = ""
    notion_database_id: str = ""

    # Brightspace via gws calendar
    brightspace_calendar_id: str = ""
    sync_days_ahead: int = 180

    # Course mappings
    courses: list[CourseMapping] = field(default_factory=list)

    # SQLite
    db_path: str = ""

    # OpenClaw
    openclaw_enabled: bool = True

    # Polling
    poll_interval_minutes: int = 30

    # Timezone
    timezone: str = "America/Indiana/Indianapolis"

    @classmethod
    def from_env(cls) -> Config:
        _load_dotenv()
        notion_key = _read_file_or_env(
            "NOTION_API_KEY",
            os.environ.get("NOTION_API_KEY_FILE"),
        )

        db_path = os.environ.get(
            "SYNC_DB_PATH",
            str(Path(__file__).resolve().parent.parent / "state.db"),
        )

        courses_json = os.environ.get("COURSES_JSON", "")
        courses = [CourseMapping(**c) for c in json.loads(courses_json)] if courses_json else []

        return cls(
            notion_api_key=notion_key,
            notion_database_id=os.environ.get(
                "NOTION_DATABASE_ID", cls.notion_database_id
            ),
            brightspace_calendar_id=os.environ.get(
                "BRIGHTSPACE_CALENDAR_ID", cls.brightspace_calendar_id
            ),
            sync_days_ahead=int(os.environ.get("SYNC_DAYS_AHEAD", "180")),
            courses=courses,
            db_path=db_path,
            openclaw_enabled=os.environ.get("OPENCLAW_ENABLED", "1") == "1",
            poll_interval_minutes=int(os.environ.get("POLL_INTERVAL_MINUTES", "30")),
            timezone=os.environ.get("TZ", cls.timezone),
        )
