"""
core/repair_engine.py
=====================
RepairEngine — crash diagnosis, fix, and relaunch orchestration.

Uses ERROR_TAXONOMY_SYSTEM (core/repair/) for classification:

  dependency_error  → pip install <package>            [DEPENDENCY_FIX]
  import_error      → add missing __init__.py files    [IMPORT_FIX]
  port_error        → kill stale processes, new port   [AUTO_FIX]
  syntax_error      → snapshot + log (no rewrite)
  runtime_error     → logged; no auto-fix
  unknown_error     → logged; no auto-fix

Singleton lock: only one repair loop per project_id at a time.
Max retries: 3 (default). Snapshots taken before every fix attempt.
Never crashes Nexus — all exceptions are caught and logged.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Set

from core.snapshot_manager import create_snapshot
from core.git_manager import checkpoint
from core.runtime.process_manager import get_manager
from core.actions.command_action import get_python_executable
from core.repair.error_classifier import classify_error, extract_package_name, extract_import_details
from core.repair.repair_tracker import record_attempt

logger = logging.getLogger(__name__)

_BACKOFF = [5.0, 10.0, 20.0]


# ── RepairEngine ───────────────────────────────────────────────────────────────

class RepairEngine:
    """
    Async repair orchestrator.  One instance shared via get_repair_engine().
    Only one repair loop may run per project_id at a time.
    """

    def __init__(self) -> None:
        self._retries: Dict[str, int] = {}
        self._active:  Set[str] = set()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(
        self,
        project_id: str,
        project_path: Path,
        launcher: Callable[..., Awaitable[bool]],
        max_retries: int = 3,
    ) -> Dict:
        """
        Monitor *project_id* and attempt auto-repair if it crashes.

        Returns {"success": bool, "attempts": int, "final_error": str}
        """
        manager = get_manager()
        project_path = Path(project_path).resolve()

        if project_id in self._active:
            logger.info("[REPAIR] '%s' — already active, skipping duplicate", project_id)
            return {"success": False, "attempts": 0, "final_error": "duplicate repair skipped"}

        self._active.add(project_id)
        try:
            return await self._run_loop(project_id, project_path, launcher, max_retries, manager)
        finally:
            self._active.discard(project_id)

    async def _run_loop(
        self,
        project_id: str,
        project_path: Path,
        launcher: Callable[..., Awaitable[bool]],
        max_retries: int,
        manager,
    ) -> Dict:
        self._retries.setdefault(project_id, 0)

        for attempt in range(1, max_retries + 1):
            backoff = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
            logger.info(
                "[REPAIR] '%s' — waiting %.0fs (attempt %d/%d)",
                project_id, backoff, attempt, max_retries,
            )
            await asyncio.sleep(backoff)

            entry = manager.get(project_id)
            if not entry:
                return {"success": False, "attempts": attempt, "final_error": "not in ProcessManager"}

            status = entry.get("status")

            if status == "running":
                logger.info("[REPAIR] '%s' is healthy — no repair needed", project_id)
                return {"success": True, "attempts": 0, "final_error": ""}

            if status != "failed":
                logger.info("[REPAIR] '%s' status=%s — stopping", project_id, status)
                return {"success": False, "attempts": attempt, "final_error": f"status={status}"}

            # ── Classify crash ────────────────────────────────────────────────
            logs = list(entry.get("logs") or [])
            crash_output = "\n".join(logs)

            category = classify_error(crash_output)
            logger.info("[CLASSIFIER] '%s' attempt=%d → category=%s", project_id, attempt, category)

            # ── Snapshot before any fix ───────────────────────────────────────
            create_snapshot(project_id, project_path, reason=f"pre-repair-{attempt}")

            # ── Apply fix ────────────────────────────────────────────────────
            fix_applied, fixed = await self._apply_fix(project_id, project_path, category, crash_output)
            record_attempt(
                project_id=project_id,
                attempt=attempt,
                error_category=category,
                error_detail=crash_output[-300:],
                fix_applied=fix_applied,
                success=False,   # updated to True if relaunch succeeds below
            )

            if not fixed:
                logger.warning(
                    "[REPAIR] '%s' — no auto-fix for category='%s', giving up",
                    project_id, category,
                )
                return {
                    "success": False,
                    "attempts": attempt,
                    "final_error": f"no fix available for {category}",
                }

            # ── Relaunch ──────────────────────────────────────────────────────
            self._retries[project_id] = attempt
            logger.info("[REPAIR] '%s' — relaunching (attempt %d/%d)", project_id, attempt, max_retries)

            try:
                launched = await launcher(project_id, project_path, force=True)
            except Exception as exc:
                logger.error("[REPAIR] '%s' — launcher error: %s", project_id, exc)
                return {"success": False, "attempts": attempt, "final_error": str(exc)}

            if not launched:
                logger.error("[REPAIR] '%s' — relaunch failed (attempt %d)", project_id, attempt)
                return {"success": False, "attempts": attempt, "final_error": "relaunch returned False"}

            # Mark this attempt as successful in tracker
            record_attempt(
                project_id=project_id,
                attempt=attempt,
                error_category=category,
                error_detail="",
                fix_applied=fix_applied + " + relaunched",
                success=True,
            )

        logger.warning("[REPAIR] '%s' — exhausted %d retries", project_id, max_retries)
        return {"success": False, "attempts": max_retries, "final_error": "max retries exhausted"}

    def get_retry_count(self, project_id: str) -> int:
        return self._retries.get(project_id, 0)

    # ── Fix dispatch ──────────────────────────────────────────────────────────

    async def _apply_fix(
        self,
        project_id: str,
        project_path: Path,
        category: str,
        crash_output: str,
    ) -> tuple[str, bool]:
        """
        Dispatch to the right fix strategy.
        Returns (fix_description, success_bool).
        """
        if category == "dependency_error":
            return await self._fix_dependency(project_id, project_path, crash_output)

        if category == "import_error":
            return await self._fix_import(project_id, project_path, crash_output)

        if category == "port_error":
            return await self._fix_port(project_id, project_path)

        # syntax_error, runtime_error, unknown_error → no auto-fix
        logger.warning("[AUTO_FIX] '%s' — no handler for category=%s", project_id, category)
        return ("none", False)

    # ── Dependency fix ────────────────────────────────────────────────────────

    async def _fix_dependency(
        self, project_id: str, project_path: Path, crash_output: str
    ) -> tuple[str, bool]:
        pkg = extract_package_name(crash_output)
        if not pkg:
            logger.warning("[DEPENDENCY_FIX] '%s' — could not extract package name", project_id)
            return ("extract_failed", False)

        python = get_python_executable()
        logger.info("[DEPENDENCY_FIX] '%s' — pip install %s", project_id, pkg)

        try:
            proc = await asyncio.create_subprocess_exec(
                python, "-m", "pip", "install", pkg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_b = await proc.communicate()

            if proc.returncode == 0:
                logger.info("[DEPENDENCY_FIX] '%s' — pip install %s OK", project_id, pkg)
                checkpoint(project_path, f"[AI] repaired runtime: pip install {pkg}")
                return (f"pip install {pkg}", True)

            err = stderr_b.decode("utf-8", errors="replace").strip()[-200:]
            logger.warning("[DEPENDENCY_FIX] '%s' — pip install %s FAILED: %s", project_id, pkg, err)
            return (f"pip install {pkg} failed", False)

        except Exception as exc:
            logger.error("[DEPENDENCY_FIX] '%s' — error: %s", project_id, exc)
            return ("pip error", False)

    # ── Import fix ────────────────────────────────────────────────────────────

    async def _fix_import(
        self, project_id: str, project_path: Path, crash_output: str
    ) -> tuple[str, bool]:
        """
        Add missing __init__.py files for all Python package directories.
        This fixes the common case where the AI generates a package structure
        but omits __init__.py, causing 'cannot import name X from Y'.
        """
        logger.info("[IMPORT_FIX] '%s' — scanning for missing __init__.py", project_id)
        created = []

        try:
            for dirpath in project_path.rglob("*"):
                if not dirpath.is_dir():
                    continue
                # Skip hidden dirs, __pycache__, and virtualenvs
                if any(part.startswith(".") or part == "__pycache__" or part == "venv"
                       for part in dirpath.parts):
                    continue
                # A dir with .py files is a package — ensure __init__.py exists
                py_files = list(dirpath.glob("*.py"))
                init_file = dirpath / "__init__.py"
                if py_files and not init_file.exists():
                    init_file.write_text("", encoding="utf-8")
                    created.append(str(init_file.relative_to(project_path)))
                    logger.info("[IMPORT_FIX] created %s", init_file.relative_to(project_path))

            if created:
                desc = f"add __init__.py: {', '.join(created[:5])}"
                checkpoint(project_path, f"[AI] repaired imports: {desc}")
                logger.info("[IMPORT_FIX] '%s' — fixed %d missing __init__.py file(s)", project_id, len(created))
                return (desc, True)

            logger.warning("[IMPORT_FIX] '%s' — no missing __init__.py found", project_id)
            return ("no __init__.py to add", False)

        except Exception as exc:
            logger.error("[IMPORT_FIX] '%s' — error: %s", project_id, exc)
            return ("import fix error", False)

    # ── Port fix ──────────────────────────────────────────────────────────────

    async def _fix_port(
        self, project_id: str, project_path: Path
    ) -> tuple[str, bool]:
        """
        Kill the stale process registered in ProcessManager for this project
        so the next launch can get a clean port via PortAllocator.
        """
        logger.info("[AUTO_FIX] '%s' — port_error: killing stale process", project_id)
        try:
            import psutil as _psutil
            manager = get_manager()
            entry = manager.get(project_id)
            if entry:
                pid = entry.get("pid")
                if pid:
                    try:
                        p = _psutil.Process(int(pid))
                        p.terminate()
                        p.wait(timeout=3)
                        logger.info("[AUTO_FIX] '%s' — killed stale pid=%s", project_id, pid)
                    except (_psutil.NoSuchProcess, _psutil.TimeoutExpired, ProcessLookupError):
                        pass
            return ("killed stale process", True)

        except ImportError:
            logger.warning("[AUTO_FIX] '%s' — psutil not available for port fix", project_id)
            return ("psutil missing", True)  # still attempt relaunch with new port
        except Exception as exc:
            logger.error("[AUTO_FIX] '%s' — port fix error: %s", project_id, exc)
            return ("port fix error", True)   # still attempt relaunch


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[RepairEngine] = None


def get_repair_engine() -> RepairEngine:
    """Return the global RepairEngine singleton."""
    global _instance
    if _instance is None:
        _instance = RepairEngine()
    return _instance
