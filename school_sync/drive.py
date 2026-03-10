"""Google Drive integration via gws CLI for persistent PDF storage."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT_FOLDER_NAME = "School Sync"


def _gws(
    *args: str,
    params: dict | None = None,
    body: dict | None = None,
    upload: str | None = None,
) -> dict:
    """Run a gws drive command and return parsed JSON output."""
    cmd = ["gws", "drive", *args]
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    if upload is not None:
        cmd += ["--upload", upload]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"gws failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _find_folder(name: str, parent_id: str | None = None) -> str | None:
    """Find a folder by name, optionally within a parent. Returns folder ID or None."""
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    data = _gws("files", "list", params={"q": q, "pageSize": 1})
    files = data.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(name: str, parent_id: str | None = None) -> str:
    """Create a folder and return its ID."""
    meta: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    data = _gws("files", "create", body=meta)
    log.info("Created Drive folder %r (id=%s)", name, data["id"])
    return data["id"]


def _find_or_create_folder(name: str, parent_id: str | None = None) -> str:
    """Find an existing folder or create one. Returns folder ID."""
    fid = _find_folder(name, parent_id)
    if fid:
        return fid
    return _create_folder(name, parent_id)


def _find_file(name: str, parent_id: str) -> str | None:
    """Find a file by name within a parent folder. Returns file ID or None."""
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    data = _gws("files", "list", params={"q": q, "pageSize": 1})
    files = data.get("files", [])
    return files[0]["id"] if files else None


def upload_pdf(local_path: Path, course: str) -> str:
    """Upload a PDF to Drive under School Sync/{course}/.

    Returns the permanent Drive view URL.
    Skips upload if a file with the same name already exists in the folder.
    """
    root_id = _find_or_create_folder(_ROOT_FOLDER_NAME)
    course_id = _find_or_create_folder(course, root_id)

    filename = local_path.name
    existing = _find_file(filename, course_id)
    if existing:
        log.info("PDF already on Drive: %s (id=%s)", filename, existing)
        return f"https://drive.google.com/file/d/{existing}/view"

    data = _gws(
        "files", "create",
        body={"name": filename, "parents": [course_id]},
        upload=str(local_path),
    )
    file_id = data["id"]
    log.info("Uploaded PDF to Drive: %s (id=%s)", filename, file_id)
    return f"https://drive.google.com/file/d/{file_id}/view"
