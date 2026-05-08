"""
SnapshotManager — create, validate, sign, and manage system snapshots for Nexus BNL.

Each snapshot is a compressed ZIP archive stored at:
    data/recovery/snapshots/{snapshot_id}.zip

The archive contains:
    - All Nexus SQLite databases (data/*.db)
    - JSON configuration files (chat_states.json etc.)
    - Core module __init__.py files (for integrity reference)
    - MANIFEST.json — SHA256 of every included file + self-signature

Snapshot lifecycle:
    PENDING   → being created
    VALID     → created and self-verified OK
    INVALID   → failed verification
    SAFE      → promoted by SafeCheckpoint (requires passing IntegrityValidator)
    CORRUPTED → detected bad; moved to quarantine/
    DELETED   → soft-deleted from DB

Usage:
    mgr = get_snapshot_manager()
    snap = mgr.create_snapshot(label="pre-update", created_by="system")
    mgr.validate_snapshot(snap["snapshot_id"])
    mgr.sign_snapshot(snap["snapshot_id"])
"""

import json
import logging
import shutil
import sqlite3
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.recovery.immutable_audit_log import ImmutableAuditLog, get_audit_log, DB_PATH
from core.recovery.integrity_validator import IntegrityValidator, IntegrityReport

logger = logging.getLogger(__name__)

# ── Directory layout ───────────────────────────────────────────────────────────

RECOVERY_ROOT  = Path("data/recovery")
SNAPSHOT_DIR   = RECOVERY_ROOT / "snapshots"
QUARANTINE_DIR = RECOVERY_ROOT / "quarantine"
FORENSICS_DIR  = RECOVERY_ROOT / "forensics"

# Files captured in every snapshot (relative to project root)
SNAPSHOT_TARGETS: List[str] = [
    # All Nexus databases
    "data/nexus_agents.db",
    "data/nexus_security.db",
    "data/nexus_sandbox.db",
    "data/nexus_isolation.db",
    "data/nexus_recovery.db",
    # Runtime state
    "chat_states.json",
    # Core module roots (integrity anchors)
    "core/agents/__init__.py",
    "core/agents/nexus_registry.py",
    "core/security/__init__.py",
    "core/security/capability_guard.py",
    "core/security/permissions.py",
    "core/sandbox/__init__.py",
    "core/sandbox/sandbox_manager.py",
    "core/isolation/__init__.py",
    "core/isolation/isolation_manager.py",
    "core/recovery/__init__.py",
    "core/recovery/snapshot_manager.py",
]


class SnapshotManager:
    """Thread-safe singleton for snapshot lifecycle management."""

    _instance: Optional["SnapshotManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SnapshotManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            for d in (SNAPSHOT_DIR, QUARANTINE_DIR, FORENSICS_DIR):
                d.mkdir(parents=True, exist_ok=True)
            self._db     = str(DB_PATH)
            self._audit  = get_audit_log()
            self._val    = IntegrityValidator()
            self._initialized = True
            logger.info("[RECOVERY] SnapshotManager initialized")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Create ─────────────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        label: str = "",
        created_by: str = "system",
        notes: str = "",
        extra_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a snapshot ZIP of all critical system state.
        Returns the snapshot record dict.
        """
        snapshot_id = str(uuid.uuid4())
        zip_path    = SNAPSHOT_DIR / f"{snapshot_id}.zip"
        base        = Path(".")

        # Collect files
        all_targets = list(SNAPSHOT_TARGETS)
        if extra_files:
            all_targets.extend(extra_files)

        # De-duplicate and filter to existing paths
        paths = []
        for t in dict.fromkeys(all_targets):  # preserve order, deduplicate
            p = base / t
            if p.exists():
                paths.append(p)
            else:
                logger.debug("[RECOVERY] Snapshot target not found (skipped): %s", t)

        # Build manifest BEFORE zipping (so we can include it inside)
        manifest = self._val.build_manifest(paths, snapshot_id, root=base)

        # Write ZIP
        total_size = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in paths:
                arcname = str(p).replace("\\", "/")
                zf.write(p, arcname=arcname)
                total_size += p.stat().st_size

            # Write manifest inside the archive
            manifest_bytes = json.dumps(manifest, indent=2).encode()
            zf.writestr("MANIFEST.json", manifest_bytes)

        zip_size = zip_path.stat().st_size
        sha256_manifest = manifest.get("manifest_sha256", "")

        # Persist to DB
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO snapshots
                   (snapshot_id, label, status, sha256_manifest, archived_path,
                    files_count, size_bytes, created_by, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, label, "PENDING", sha256_manifest,
                 str(zip_path), len(paths), zip_size, created_by, notes),
            )

        self._audit.append(
            "SNAPSHOT_CREATED",
            f"Snapshot {snapshot_id[:8]} created: {len(paths)} files {zip_size//1024}KB",
            {"snapshot_id": snapshot_id, "label": label, "files": len(paths)},
        )
        logger.info("[RECOVERY] Snapshot created: %s (%d files, %dKB)",
                    snapshot_id[:16], len(paths), zip_size // 1024)

        # Auto-validate immediately
        report = self.validate_snapshot(snapshot_id)
        snap = self.get_snapshot(snapshot_id)
        return snap or {"snapshot_id": snapshot_id, "status": "PENDING"}

    # ── Validate ───────────────────────────────────────────────────────────────

    def validate_snapshot(self, snapshot_id: str) -> IntegrityReport:
        """Verify ZIP contents against the embedded manifest. Updates DB status."""
        snap = self.get_snapshot(snapshot_id)
        if not snap:
            return IntegrityReport(snapshot_id=snapshot_id, result="FAIL",
                                   details={"error": "Snapshot not found"})

        zip_path = Path(snap["archived_path"])
        manifest = self._load_manifest_from_zip(zip_path)

        if manifest is None:
            report = IntegrityReport(snapshot_id=snapshot_id, result="FAIL",
                                     details={"error": "Cannot read MANIFEST.json from archive"})
        else:
            report = self._val.verify_snapshot_zip(snapshot_id, zip_path, manifest)

        new_status = "VALID" if report.passed() else "INVALID"
        with self._conn() as conn:
            conn.execute(
                """UPDATE snapshots SET status=?, validated_at=? WHERE snapshot_id=?""",
                (new_status, self._now(), snapshot_id),
            )
            conn.execute(
                """INSERT INTO integrity_checks
                   (check_id, snapshot_id, files_checked, files_ok, files_corrupted,
                    files_missing, result, details)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), snapshot_id,
                 report.files_checked, report.files_ok,
                 len(report.files_corrupted), len(report.files_missing),
                 report.result, json.dumps(report.to_dict())),
            )

        self._audit.append(
            "SNAPSHOT_VALIDATED",
            f"Snapshot {snapshot_id[:8]} validation: {report.result}",
            {"snapshot_id": snapshot_id, "result": report.result,
             "corrupted": len(report.files_corrupted), "missing": len(report.files_missing)},
        )
        return report

    def sign_snapshot(self, snapshot_id: str) -> str:
        """Sign snapshot and store signature. Returns signature hex."""
        snap = self.get_snapshot(snapshot_id)
        if not snap:
            return ""
        zip_path = Path(snap["archived_path"])
        manifest = self._load_manifest_from_zip(zip_path)
        if not manifest:
            return ""
        sig = self._val.sign_manifest(manifest)
        with self._conn() as conn:
            conn.execute(
                "UPDATE snapshots SET sha256_manifest=?, signed_at=? WHERE snapshot_id=?",
                (sig, self._now(), snapshot_id),
            )
        self._audit.append("SNAPSHOT_SIGNED", f"Snapshot {snapshot_id[:8]} signed", {"signature": sig[:16]})
        return sig

    # ── List / Get ─────────────────────────────────────────────────────────────

    def list_snapshots(
        self,
        status: Optional[str] = None,
        checkpoint_level: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status=?"); params.append(status)
        if checkpoint_level:
            clauses.append("checkpoint_level=?"); params.append(checkpoint_level)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM snapshots {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_latest_safe(self) -> Optional[Dict[str, Any]]:
        """Return the most recent SAFE/TRUSTED/STABLE snapshot."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM snapshots
                   WHERE checkpoint_level IN ('SAFE','TRUSTED','STABLE')
                   AND status IN ('VALID','SAFE','TRUSTED','STABLE')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    # ── Delete / Quarantine ────────────────────────────────────────────────────

    def delete_corrupted_snapshot(self, snapshot_id: str) -> bool:
        """Move corrupted snapshot to quarantine directory and mark deleted."""
        snap = self.get_snapshot(snapshot_id)
        if not snap:
            return False
        zip_path = Path(snap["archived_path"])
        if zip_path.exists():
            dest = QUARANTINE_DIR / zip_path.name
            try:
                shutil.move(str(zip_path), str(dest))
                logger.info("[RECOVERY] Corrupted snapshot quarantined: %s → %s", zip_path.name, dest)
            except Exception as exc:
                logger.error("[RECOVERY] Cannot move to quarantine: %s", exc)
        with self._conn() as conn:
            conn.execute(
                "UPDATE snapshots SET status='DELETED' WHERE snapshot_id=?", (snapshot_id,)
            )
        self._audit.append(
            "SNAPSHOT_DELETED",
            f"Corrupted snapshot {snapshot_id[:8]} deleted → quarantine",
            {"snapshot_id": snapshot_id},
        )
        return True

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_manifest_from_zip(zip_path: Path) -> Optional[Dict[str, Any]]:
        """Extract and parse MANIFEST.json from inside a snapshot ZIP."""
        if not zip_path.exists():
            return None
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if "MANIFEST.json" not in zf.namelist():
                    return None
                data = zf.read("MANIFEST.json")
                return json.loads(data.decode())
        except Exception as exc:
            logger.error("[RECOVERY] Cannot read manifest from %s: %s", zip_path, exc)
            return None

    def get_manifest(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        snap = self.get_snapshot(snapshot_id)
        if not snap:
            return None
        return self._load_manifest_from_zip(Path(snap["archived_path"]))

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total   = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            valid   = conn.execute("SELECT COUNT(*) FROM snapshots WHERE status='VALID'").fetchone()[0]
            safe    = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE checkpoint_level IN ('SAFE','STABLE','TRUSTED')"
            ).fetchone()[0]
            deleted = conn.execute("SELECT COUNT(*) FROM snapshots WHERE status='DELETED'").fetchone()[0]
            checks  = conn.execute("SELECT COUNT(*) FROM integrity_checks").fetchone()[0]
        latest = self.get_latest_safe()
        return {
            "total_snapshots": total,
            "valid_snapshots": valid,
            "safe_snapshots":  safe,
            "deleted":         deleted,
            "integrity_checks": checks,
            "latest_safe_id":  latest["snapshot_id"] if latest else None,
            "latest_safe_at":  latest["created_at"]  if latest else None,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_mgr: Optional[SnapshotManager] = None
_mgr_lock = threading.Lock()


def get_snapshot_manager() -> SnapshotManager:
    global _mgr
    if _mgr is None:
        with _mgr_lock:
            if _mgr is None:
                _mgr = SnapshotManager()
    return _mgr
