"""Watches a local folder for new TRN / National ID files dropped there by
the other system (as a ZIP named after the Transaction Reference Number /
National ID Card Number) and copies each new one into a separate local
sync/backup folder.

"New" means: the file's on-disk modified time is newer than the newest
modified time already recorded in trn_sync_log for a successfully synced
file. This intentionally does not care about filenames matching any
particular pattern -- whatever the other system drops in the source folder
gets copied over as-is, so the original file (and its name, e.g. the
TRN/National ID number) is preserved.

This module has no Flask/DB imports at the top level beyond what's needed to
call into app.repository -- it's meant to be safe to call both from a
request (the "Check for New Files Now" button) and from the background
scheduler thread.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TrnSyncResult:
    ok: bool
    message: str
    synced_count: int = 0
    error_count: int = 0
    synced_filenames: list[str] = field(default_factory=list)


def _file_modified_at_iso(path: Path) -> str:
    # Stored/compared as ISO-8601 UTC so plain string comparison ("newer
    # than") works the same way SQL's MAX() comparison does.
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def check_for_new_trn_files() -> TrnSyncResult:
    """Looks at the configured source folder for files newer than the last
    synced one and copies each into the configured destination folder.

    Safe to call any time: if either folder isn't configured yet, or the
    source folder doesn't exist (e.g. the other system's drive isn't mounted
    right now), this does nothing harmful and just reports why.
    """
    from ..repository import (
        get_trn_sync_settings,
        is_file_already_synced,
        latest_synced_file_modified_at,
        record_trn_sync_result,
    )

    settings = get_trn_sync_settings()
    source_folder = settings["source_folder"]
    dest_folder = settings["dest_folder"]

    if not source_folder or not dest_folder:
        return TrnSyncResult(
            ok=False,
            message="Set both the source folder and the sync/backup folder before checking for files.",
        )

    source_path = Path(source_folder)
    dest_path = Path(dest_folder)

    if not source_path.is_dir():
        return TrnSyncResult(ok=False, message=f'Source folder not found: "{source_folder}"')

    try:
        dest_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return TrnSyncResult(ok=False, message=f'Could not create/access sync folder: {exc}')

    last_synced_at = latest_synced_file_modified_at()

    # Only look at files (skip subfolders), sorted oldest-modified first so
    # if several are new, they're copied and logged in chronological order.
    candidates = sorted(
        (p for p in source_path.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )

    synced_count = 0
    error_count = 0
    synced_filenames: list[str] = []

    for src_file in candidates:
        modified_at = _file_modified_at_iso(src_file)

        if last_synced_at and modified_at <= last_synced_at:
            continue
        if is_file_already_synced(src_file.name, modified_at):
            continue

        dest_file = dest_path / src_file.name
        # Avoid clobbering an existing file of the same name in the sync
        # folder (e.g. a file dropped again with the same name but a newer
        # modified time) by adding a timestamp suffix instead of overwriting.
        if dest_file.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            dest_file = dest_path / f"{src_file.stem}_{stamp}{src_file.suffix}"

        try:
            shutil.copy2(src_file, dest_file)
        except OSError as exc:
            logger.exception("Failed to copy %s to sync folder", src_file)
            record_trn_sync_result(
                filename=src_file.name,
                source_path=str(src_file),
                dest_path=None,
                file_modified_at=modified_at,
                status="error",
                error_message=str(exc),
            )
            error_count += 1
            continue

        record_trn_sync_result(
            filename=src_file.name,
            source_path=str(src_file),
            dest_path=str(dest_file),
            file_modified_at=modified_at,
            status="synced",
        )
        synced_count += 1
        synced_filenames.append(src_file.name)

    if error_count and not synced_count:
        message = f"Checked source folder -- {error_count} file(s) failed to copy."
    elif synced_count:
        message = f"Synced {synced_count} new file(s) to the sync folder."
        if error_count:
            message += f" ({error_count} failed.)"
    else:
        message = "Checked source folder -- no new files."

    return TrnSyncResult(
        ok=True,
        message=message,
        synced_count=synced_count,
        error_count=error_count,
        synced_filenames=synced_filenames,
    )
