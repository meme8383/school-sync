# school_sync

Minimal Python service that polls Gradescope and Brightspace for school assignments, diffs against local SQLite state, and upserts into a Notion database. Batches change notifications to OpenClaw.

## Prerequisites

- `gradescope-cli` authenticated (`gradescope-cli login`)
- `gws` authenticated (`gws auth login`)
- Notion integration with access to School Tasks database
- Python 3.12+ (no pip dependencies — uses only stdlib + Notion REST API)

## Usage

```bash
# One-shot sync
python -m school_sync --once

# Watch mode (polls every 30 min)
python -m school_sync --watch

# Single source only
python -m school_sync --once --source gradescope
python -m school_sync --once --source brightspace

# Preview changes without applying
python -m school_sync --once --dry-run

# Verbose/debug output
python -m school_sync --once -v
```

## Configuration

Copy `.env.example` and adjust as needed. Defaults work for the existing Purdue setup — Notion key is read from `/root/.config/notion/api_key`.

## Architecture

```
sources/gradescope.py   -> gradescope-cli assignments <id>
sources/brightspace.py  -> gws calendar events list (Brightspace calendar)
         |
    models.py           -> normalized Assignment dataclass
         |
    state.py            -> SQLite diff (new / due_changed / title_changed / removed)
         |
    targets/notion.py   -> idempotent upsert by External ID
    targets/openclaw.py  -> one batched wake notification
```

## Notion field mapping

| Notion Property | Source |
|---|---|
| Name | assignment title |
| Due | due date (ISO 8601) |
| Course | course label (multi-select) |
| External ID | `bs:<ou>:<eventId>` or `gs:<courseId>:<assignmentId>` |
| Source | "Brightspace" or "Gradescope" |
| Link | source URL |
| Status | untouched (user-managed) |
| Estimate (hrs) | untouched (user-managed) |
| Docs | untouched (future: PDF uploads) |
| Notes | untouched (user-managed) |
