"""OpenClaw notification target: POST to /hooks/agent endpoint."""

from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ..models import Change, ChangeType

log = logging.getLogger(__name__)

_DEFAULT_URL = "http://127.0.0.1:18789"


def _build_message(changes: list[Change]) -> str:
    """Build a compact notification message from a batch of changes."""
    lines = [f"School Sync: {len(changes)} change(s) detected\n"]

    by_type: dict[ChangeType, list[Change]] = {}
    for ch in changes:
        by_type.setdefault(ch.change_type, []).append(ch)

    for ct in (ChangeType.NEW, ChangeType.DUE_CHANGED, ChangeType.TITLE_CHANGED, ChangeType.REMOVED):
        group = by_type.get(ct, [])
        if not group:
            continue
        lines.append(f"--- {ct.value.upper()} ({len(group)}) ---")
        for ch in group:
            desc = ch.describe()
            if ch.assignment.pdf_url:
                desc += " [PDF available in Docs]"
            lines.append(f"  {desc}")

    return "\n".join(lines)


def _get_config() -> tuple[str, str]:
    """Get gateway URL and hooks token from env or OpenClaw config."""
    url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
    token = os.environ.get("OPENCLAW_HOOKS_TOKEN", "").strip()

    if not url or not token:
        # Read from openclaw.json
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        try:
            with open(config_path) as f:
                cfg = _json.load(f)
            gw = cfg.get("gateway", {})
            if not url:
                port = gw.get("port", 18789)
                url = f"http://127.0.0.1:{port}"
            if not token:
                token = gw.get("auth", {}).get("token", "")
                # Also check hooks-specific token
                hooks_token = cfg.get("hooks", {}).get("token", "")
                if hooks_token:
                    token = hooks_token
        except (FileNotFoundError, _json.JSONDecodeError):
            if not url:
                url = _DEFAULT_URL

    return url, token


def notify(
    changes: list[Change],
    enabled: bool = True,
    database_id: str = "",
    page_ids: dict[str, str] | None = None,
) -> None:
    """Send one batched notification to OpenClaw via POST /hooks/agent."""
    if not enabled or not changes:
        return

    summary = _build_message(changes)
    run_ts = datetime.now(timezone.utc).isoformat()

    # Build metadata block for the agent
    changed_pages = page_ids or {}
    meta_lines = [
        f"Notion database: {database_id}",
        f"Run timestamp: {run_ts}",
        f"Changed page IDs: {', '.join(changed_pages.values()) if changed_pages else 'none (removals only)'}",
    ]
    metadata = "\n".join(meta_lines)

    prompt = (
        "The school assignment sync just ran and detected changes. "
        "Summarize what's new or changed concisely for the user. "
        "Highlight anything due soon.\n\n"
        f"{summary}\n\n"
        f"--- Metadata ---\n{metadata}"
    )
    log.info("Sending OpenClaw agent hook:\n%s", summary)

    url, token = _get_config()
    endpoint = f"{url}/hooks/agent"

    telegram_to = os.environ.get("OPENCLAW_TELEGRAM_TO", "")
    payload = _json.dumps({
        "message": prompt,
        "name": "School Sync",
        "channel": "telegram",
        "to": telegram_to,
        "deliver": True,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    req = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            log.info("OpenClaw agent hook sent (HTTP %d)", resp.status)
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log.warning("OpenClaw agent hook failed (HTTP %d): %s", e.code, body)
    except URLError as e:
        log.warning("OpenClaw gateway unreachable: %s", e.reason)
    except Exception:
        log.exception("Failed to send OpenClaw agent hook")
