"""
core/snapshot_manager.py
=========================
Automatic filesystem snapshots before any destructive operation.

Snapshots are stored under:
    snapshots/<project_id>/<YYYY-MM-DD_HH-MM-SS>/

Never crash Nexus — all operations are best-effort with full logging.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path("snapshots").resolve()


def create_snapshot(
    project_id: str,
    project_path: Path,
    reason: str = "",
) -> Optional[Path]:
    """
    Copy *project_path* into a timestamped snapshot directory.

    Returns the snapshot Path on success, None on failure.
    Logs [SNAPSHOT] created / failure.
    """
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest = SNAPSHOTS_DIR / project_id / ts
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(project_path), str(dest))
        logger.info(
            "[SNAPSHOT] created  project=%s  ts=%s  reason=%s",
            project_id, ts, reason or "(none)",
        )
        return dest
    except Exception as exc:
        logger.warning(
            "[SNAPSHOT] failed to create snapshot for '%s': %s", project_id, exc
        )
        return None


def latest_snapshot(project_id: str) -> Optional[Path]:
    """Return the most recent snapshot directory, or None if none exist."""
    parent = SNAPSHOTS_DIR / project_id
    if not parent.exists():
        return None
    dirs = sorted(
        (d for d in parent.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


def latest_snapshot_timestamp(project_id: str) -> Optional[str]:
    """Return the timestamp string of the most recent snapshot, or None."""
    snap = latest_snapshot(project_id)
    return snap.name if snap else None


def restore_snapshot(
    project_id: str,
    project_path: Path,
    snapshot_dir: Optional[Path] = None,
) -> bool:
    """
    Overwrite *project_path* with the contents of *snapshot_dir* (or the
    latest snapshot for *project_id*).

    Returns True on success.
    Logs [SNAPSHOT] restored / failure.
    """
    src = snapshot_dir or latest_snapshot(project_id)
    if src is None or not src.exists():
        logger.warning(
            "[SNAPSHOT] no snapshot found for '%s' — cannot restore", project_id
        )
        return False
    try:
        if project_path.exists():
            shutil.rmtree(str(project_path))
        shutil.copytree(str(src), str(project_path))
        logger.info(
            "[SNAPSHOT] restored  project=%s  from=%s", project_id, src.name
        )
        return True
    except Exception as exc:
        logger.warning(
            "[SNAPSHOT] restore failed for '%s': %s", project_id, exc
        )
        return False


def list_snapshots(project_id: str) -> List[str]:
    """Return all snapshot timestamp strings for *project_id*, newest first."""
    parent = SNAPSHOTS_DIR / project_id
    if not parent.exists():
        return []
    return sorted(
        (d.name for d in parent.iterdir() if d.is_dir()),
        reverse=True,
    )
