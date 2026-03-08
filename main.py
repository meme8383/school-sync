"""School assignment sync: Gradescope + Brightspace -> Notion.

Usage:
    python -m school_sync.main --once          # one-shot sync
    python -m school_sync.main --watch         # poll on interval
    python -m school_sync.main --once --source gradescope   # single source
    python -m school_sync.main --once --source brightspace  # single source
    python -m school_sync.main --once --dry-run             # preview changes
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .config import Config
from .models import Change, ChangeType
from .state import StateDB
from .sources import gradescope, brightspace
from .targets import notion, openclaw

log = logging.getLogger("school_sync")

_SHUTDOWN = False


def _handle_signal(sig, frame):
    global _SHUTDOWN
    log.info("Shutdown requested")
    _SHUTDOWN = True


def sync_once(cfg: Config, db: StateDB, source_filter: str | None = None, dry_run: bool = False) -> list[Change]:
    """Run one sync cycle. Returns list of changes detected."""
    # 1. Fetch from sources
    all_assignments: list[Assignment] = []

    if source_filter in (None, "gradescope"):
        try:
            gs = gradescope.fetch_all(cfg)
            all_assignments.extend(gs)
        except Exception:
            log.exception("Gradescope fetch failed")

    if source_filter in (None, "brightspace"):
        try:
            bs = brightspace.fetch_all(cfg)
            all_assignments.extend(bs)
        except Exception:
            log.exception("Brightspace fetch failed")

    log.info("Fetched %d total assignments", len(all_assignments))

    # 2. Diff against stored state
    changes = db.diff(all_assignments)
    if not changes:
        log.info("No changes detected")
        return []

    for ch in changes:
        log.info("  %s", ch.describe())

    if dry_run:
        log.info("Dry run: %d changes would be applied", len(changes))
        return changes

    # 3. Apply to Notion
    page_ids = notion.apply_changes(cfg, changes, db.get_notion_page_id)

    # 4. Update local state (single transaction)
    for ch in changes:
        if ch.change_type == ChangeType.REMOVED:
            db.mark_removed(ch.assignment.external_id, commit=False)
        else:
            page_id = page_ids.get(ch.assignment.external_id)
            db.upsert(ch.assignment, page_id, commit=False)
    db.commit()

    # 5. Notify OpenClaw (one batched message)
    openclaw.notify(
        changes,
        enabled=cfg.openclaw_enabled,
        database_id=cfg.notion_database_id,
        page_ids=page_ids,
    )

    log.info("Sync complete: %d changes applied", len(changes))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description="School assignment sync")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run one sync cycle")
    mode.add_argument("--watch", action="store_true", help="Poll on interval")
    parser.add_argument("--source", choices=["gradescope", "brightspace"],
                        help="Sync only one source")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = Config.from_env()
    if not cfg.notion_api_key:
        log.error("No Notion API key found. Set NOTION_API_KEY or NOTION_API_KEY_FILE.")
        sys.exit(1)

    db = StateDB(cfg.db_path)

    if args.once:
        changes = sync_once(cfg, db, source_filter=args.source, dry_run=args.dry_run)
        db.close()
        sys.exit(0)

    if args.watch:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        log.info("Watching every %d minutes (Ctrl+C to stop)", cfg.poll_interval_minutes)

        while not _SHUTDOWN:
            try:
                sync_once(cfg, db, source_filter=args.source, dry_run=args.dry_run)
            except Exception:
                log.exception("Sync cycle failed")

            for _ in range(cfg.poll_interval_minutes * 60):
                if _SHUTDOWN:
                    break
                time.sleep(1)

        log.info("Shutting down")
        db.close()


if __name__ == "__main__":
    main()
