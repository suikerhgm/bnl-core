"""
IntegrityValidator — SHA256-based file and snapshot integrity verification for Nexus BNL.

Responsibilities:
  - Compute SHA256 of individual files
  - Build and verify snapshot manifests
  - Detect corruption, missing files, and unauthorized modifications
  - Detect crash loops (rapid restart patterns)
  - Detect broken registry / DB integrity

Usage:
    v = IntegrityValidator()
    manifest = v.build_manifest(file_paths)
    ok, report = v.verify_manifest(manifest, snapshot_zip_path)
    sig = v.sign_manifest(manifest)
    ok = v.verify_signature(manifest, sig)
"""

import hashlib
import json
import logging
import sqlite3
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Critical files that MUST exist for a healthy system ───────────────────────

CRITICAL_FILES = [
    "data/nexus_agents.db",
    "data/nexus_security.db",
    "data/nexus_sandbox.db",
    "data/nexus_isolation.db",
    "data/nexus_recovery.db",
    "core/agents/__init__.py",
    "core/agents/nexus_registry.py",
    "core/security/__init__.py",
    "core/security/capability_guard.py",
    "core/sandbox/__init__.py",
    "core/sandbox/sandbox_manager.py",
    "core/isolation/__init__.py",
    "core/isolation/isolation_manager.py",
    "core/recovery/__init__.py",
]

# ── Crash loop detection ───────────────────────────────────────────────────────

_CRASH_WINDOW_SEC   = 60
_CRASH_LOOP_THRESHOLD = 5   # ≥5 restarts in 60s = crash loop


@dataclass
class IntegrityReport:
    """Result of a manifest verification pass."""
    snapshot_id:     str
    checked_at:      str   = field(default_factory=lambda: _now())
    files_checked:   int   = 0
    files_ok:        int   = 0
    files_corrupted: List[str] = field(default_factory=list)
    files_missing:   List[str] = field(default_factory=list)
    unauthorized:    List[str] = field(default_factory=list)
    result:          str   = "UNKNOWN"   # PASS / FAIL / PARTIAL
    chain_intact:    bool  = True
    details:         Dict  = field(default_factory=dict)

    def passed(self) -> bool:
        return self.result == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id":     self.snapshot_id,
            "checked_at":      self.checked_at,
            "files_checked":   self.files_checked,
            "files_ok":        self.files_ok,
            "files_corrupted": self.files_corrupted,
            "files_missing":   self.files_missing,
            "unauthorized":    self.unauthorized,
            "result":          self.result,
            "chain_intact":    self.chain_intact,
            "details":         self.details,
        }


class IntegrityValidator:
    """
    Stateless validator. All methods are pure functions — no shared state.
    Use crash_tracker for loop detection (stateful, per-validator instance).
    """

    def __init__(self) -> None:
        self._crash_times: deque = deque()

    # ── SHA256 helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def sha256_file(path: Path) -> Optional[str]:
        """Compute SHA256 of a file. Returns None if file cannot be read."""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except (OSError, PermissionError) as exc:
            logger.warning("[RECOVERY] sha256_file(%s) failed: %s", path, exc)
            return None

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_string(s: str) -> str:
        return hashlib.sha256(s.encode()).hexdigest()

    # ── Manifest operations ────────────────────────────────────────────────────

    def build_manifest(
        self,
        file_paths: List[Path],
        snapshot_id: str,
        root: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Build a manifest dict: {relative_path: sha256, ...} + metadata.
        `root` is the base directory for computing relative keys.
        """
        root = root or Path(".")
        manifest: Dict[str, str] = {}
        missing: List[str] = []

        for p in file_paths:
            key = str(p.relative_to(root)) if p.is_absolute() and root != Path(".") else str(p)
            key = key.replace("\\", "/")  # normalize to forward slashes
            if not p.exists():
                missing.append(key)
                continue
            digest = self.sha256_file(p)
            if digest:
                manifest[key] = digest
            else:
                missing.append(key)

        full = {
            "snapshot_id":  snapshot_id,
            "created_at":   _now(),
            "files":        manifest,
            "missing":      missing,
            "file_count":   len(manifest),
        }
        # Sign the manifest itself
        canonical = json.dumps(full, sort_keys=True)
        full["manifest_sha256"] = self.sha256_string(canonical)
        return full

    def sign_manifest(self, manifest: Dict[str, Any]) -> str:
        """
        Return a deterministic SHA256 signature of the manifest content.
        Excludes the 'manifest_sha256' field itself before signing.
        """
        to_sign = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        canonical = json.dumps(to_sign, sort_keys=True)
        return self.sha256_string(canonical)

    def verify_signature(self, manifest: Dict[str, Any], expected_sig: str) -> bool:
        """Verify the manifest signature."""
        computed = self.sign_manifest(manifest)
        ok = computed == expected_sig
        if not ok:
            logger.warning("[RECOVERY] Manifest signature mismatch")
        return ok

    def verify_manifest_self(self, manifest: Dict[str, Any]) -> bool:
        """Verify the manifest's own sha256 is consistent."""
        stored = manifest.get("manifest_sha256", "")
        to_check = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        canonical = json.dumps(to_check, sort_keys=True)
        computed = self.sha256_string(canonical)
        return computed == stored

    # ── Snapshot verification ──────────────────────────────────────────────────

    def verify_snapshot_zip(
        self,
        snapshot_id: str,
        zip_path: Path,
        manifest: Dict[str, Any],
    ) -> IntegrityReport:
        """
        Verify every file inside a snapshot ZIP against its manifest entry.
        Returns an IntegrityReport.
        """
        report = IntegrityReport(snapshot_id=snapshot_id)

        if not zip_path.exists():
            report.result = "FAIL"
            report.details["error"] = f"Archive not found: {zip_path}"
            return report

        # First check manifest self-consistency
        if not self.verify_manifest_self(manifest):
            report.result = "FAIL"
            report.details["manifest_error"] = "Manifest SHA256 invalid — manifest may be tampered"
            report.chain_intact = False
            return report

        expected: Dict[str, str] = manifest.get("files", {})
        report.files_checked = len(expected)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names_in_zip = set(zf.namelist())
                for rel_path, expected_hash in expected.items():
                    norm = rel_path.replace("\\", "/")
                    if norm not in names_in_zip and rel_path not in names_in_zip:
                        report.files_missing.append(rel_path)
                        continue
                    try:
                        data = zf.read(norm if norm in names_in_zip else rel_path)
                        actual_hash = self.sha256_bytes(data)
                        if actual_hash == expected_hash:
                            report.files_ok += 1
                        else:
                            report.files_corrupted.append(rel_path)
                            logger.warning("[RECOVERY] Corrupted file in snapshot: %s", rel_path)
                    except Exception as exc:
                        report.files_corrupted.append(rel_path)
                        logger.warning("[RECOVERY] Cannot read %s from zip: %s", rel_path, exc)
        except zipfile.BadZipFile:
            report.result = "FAIL"
            report.details["error"] = "Bad ZIP file — archive corrupted"
            return report
        except Exception as exc:
            report.result = "FAIL"
            report.details["error"] = str(exc)
            return report

        if report.files_corrupted or report.files_missing:
            report.result = "FAIL" if report.files_corrupted else "PARTIAL"
        else:
            report.result = "PASS"

        return report

    def verify_live_files(
        self,
        manifest: Dict[str, Any],
        base: Path = Path("."),
    ) -> IntegrityReport:
        """
        Verify live filesystem files against a manifest (without a ZIP).
        Used to detect unauthorized modifications to running files.
        """
        snap_id = manifest.get("snapshot_id", "live")
        report  = IntegrityReport(snapshot_id=snap_id)
        expected: Dict[str, str] = manifest.get("files", {})
        report.files_checked = len(expected)

        for rel_path, expected_hash in expected.items():
            p = base / rel_path
            if not p.exists():
                report.files_missing.append(rel_path)
                continue
            actual = self.sha256_file(p)
            if actual is None:
                report.files_missing.append(rel_path)
            elif actual == expected_hash:
                report.files_ok += 1
            else:
                report.unauthorized.append(rel_path)
                logger.warning("[RECOVERY] Unauthorized modification: %s", rel_path)

        if report.unauthorized:
            report.result = "FAIL"
        elif report.files_missing:
            report.result = "PARTIAL"
        else:
            report.result = "PASS"
        return report

    # ── Critical file check ────────────────────────────────────────────────────

    def check_critical_files(self, base: Path = Path(".")) -> Dict[str, Any]:
        """Check that all CRITICAL_FILES exist. Returns {missing: [], ok: []}."""
        missing, ok = [], []
        for f in CRITICAL_FILES:
            p = base / f
            if p.exists():
                ok.append(f)
            else:
                missing.append(f)
                logger.error("[RECOVERY] Critical file missing: %s", f)
        return {"missing": missing, "ok": ok, "healthy": len(missing) == 0}

    # ── DB integrity check ─────────────────────────────────────────────────────

    @staticmethod
    def check_db_integrity(db_path: Path) -> Tuple[bool, str]:
        """Run SQLite PRAGMA integrity_check. Returns (ok, message)."""
        if not db_path.exists():
            return False, f"Database not found: {db_path}"
        try:
            conn = sqlite3.connect(str(db_path))
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.close()
            ok = result == "ok"
            return ok, result
        except Exception as exc:
            return False, str(exc)

    def check_all_dbs(self, data_dir: Path = Path("data")) -> Dict[str, Any]:
        """Check integrity of all Nexus SQLite databases."""
        dbs = list(data_dir.glob("*.db"))
        results = {}
        all_ok = True
        for db in dbs:
            ok, msg = self.check_db_integrity(db)
            results[db.name] = {"ok": ok, "message": msg}
            if not ok:
                all_ok = False
                logger.error("[RECOVERY] DB integrity check FAILED: %s — %s", db.name, msg)
        return {"databases": results, "all_ok": all_ok}

    # ── Crash loop detection ───────────────────────────────────────────────────

    def record_startup(self) -> bool:
        """
        Record a startup event. Returns True if a crash loop is detected.
        Call this at application startup.
        """
        now = time.monotonic()
        self._crash_times.append(now)
        while self._crash_times and (now - self._crash_times[0]) > _CRASH_WINDOW_SEC:
            self._crash_times.popleft()
        count = len(self._crash_times)
        if count >= _CRASH_LOOP_THRESHOLD:
            logger.critical(
                "[RECOVERY] CRASH LOOP DETECTED: %d startups in %ds",
                count, _CRASH_WINDOW_SEC,
            )
            return True
        return False


# ── Helper ─────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
