"""
core/runtime/runtime_engine.py
================================
RuntimeEngine — watches generated_apps/ for new projects and auto-launches
their backend.py via uvicorn.  Integrates with ProcessManager so every
spawned process is visible in the dashboard with live log streaming,
start / stop / restart, and port detection.

Uses subprocess.Popen + daemon threads (NOT asyncio.create_subprocess_exec)
so it works reliably on Windows regardless of the active event-loop
policy — including uvicorn --reload worker processes.

Usage (FastAPI startup):
    @app.on_event("startup")
    async def _boot():
        get_engine().start()

Usage (after writing project files):
    launched = await get_engine().launch(project_id, project_path)
"""
import asyncio
import contextlib
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional, Set

from core.runtime.process_manager import get_manager, extract_port
from core.runtime.port_allocator import find_free_port
from core.actions.command_action import (
    get_run_command,
    _is_safe_command,
    get_python_executable,
)

logger = logging.getLogger(__name__)

APPS_DIR           = Path("generated_apps").resolve()
POLL_INTERVAL      = 3.0   # seconds between directory scans
MAX_REPAIR_RETRIES = 3


# ── Thread-based Popen log streaming ──────────────────────────────────────

def _popen_read_stream(
    stream,
    project_id: str,
    label: str,
    log_fh=None,       # optional open file handle for cross-process log sharing
) -> None:
    """
    Thread target: drain one Popen pipe into ProcessManager line-by-line.

    If ``log_fh`` is provided every decoded line is also appended there so
    that other server processes (e.g. the dashboard) can tail the same file
    without touching the asyncio event loop.
    """
    manager = get_manager()
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                manager.update_log(project_id, line)
                port = extract_port(line)
                if port:
                    manager.set_port(project_id, port)
                if log_fh:
                    with contextlib.suppress(Exception):
                        log_fh.write(line + "\n")
                        log_fh.flush()
    except Exception as exc:
        logger.warning("⚠️ [RE] %s drain error for '%s': %s", label, project_id, exc)
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def _popen_monitor(proc: subprocess.Popen, project_id: str) -> None:
    """Thread target: block until the process exits, then update final status."""
    rc = proc.wait()
    manager = get_manager()
    # If ProcessManager.stop() already marked the process "stopped" (explicit user
    # action), don't override it — on Windows, terminate() exits with rc=1 which
    # would otherwise look like a failure.
    entry = manager.get(project_id)
    if entry and entry.get("status") == "stopped":
        logger.info("📋 [RE] '%s' terminated (rc=%d) — status already stopped", project_id, rc)
        return
    # rc 0 = clean exit, -15 = SIGTERM (Unix)
    final_status = "stopped" if rc in (0, -15) else "failed"
    manager.set_status(project_id, final_status)
    logger.info("📋 [RE] '%s' exited rc=%d → %s", project_id, rc, final_status)


# ── RuntimeEngine ──────────────────────────────────────────────────────────

class RuntimeEngine:
    """
    Watches APPS_DIR for new project directories and auto-launches their
    backend.  Also exposes ``launch()`` for immediate execution right after
    a project is created (so there is no poll delay).

    All state lives in the ProcessManager singleton — RuntimeEngine itself
    holds only the set of known project IDs so it can detect newcomers.
    """

    def __init__(self) -> None:
        self._known: Set[str] = set()
        self._task:  Optional[asyncio.Task] = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """
        Seed the known-projects set from the current directory contents so
        existing projects are *not* re-launched on restart, then begin the
        poll loop.  Idempotent.
        """
        if self._task and not self._task.done():
            logger.debug("[RE] already running — start() ignored")
            return

        if APPS_DIR.exists():
            self._known = {d.name for d in APPS_DIR.iterdir() if d.is_dir()}
            logger.info(
                "🔄 [RE] seeded %d existing project(s) — will not re-launch",
                len(self._known),
            )

        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "🔄 [RE] started — watching %s every %.0fs  python=%s",
            APPS_DIR, POLL_INTERVAL, get_python_executable(),
        )

    def stop(self) -> None:
        """Cancel the polling loop."""
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("🛑 [RE] stopped")

    # ── Public API ─────────────────────────────────────────────────

    async def launch(self, project_id: str, project_path: Path) -> bool:
        """
        Immediately launch a specific project without waiting for the next
        poll cycle.  Registers the project as known so the poller won't
        attempt a second launch.  Schedules a repair loop in the background
        so crashes are automatically diagnosed and fixed.

        Returns True if the process was started, False on any error.
        """
        self._known.add(project_id)
        launched = await self._launch_project(project_id, project_path)
        # Schedule repair regardless of immediate success — crash may happen
        # shortly after startup (e.g. import error surfaced after 500ms guard).
        asyncio.create_task(self._repair_loop(project_id, Path(project_path)))
        return launched

    def list_running(self) -> list:
        """Return a summary of all processes managed by the engine."""
        return get_manager().list_all()

    # ── Internal ───────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                await self._scan_new_projects()
            except asyncio.CancelledError:
                logger.info("[RE] poll loop cancelled")
                break
            except Exception as exc:
                logger.warning("⚠️ [RE] poll error: %s", exc)

    async def _scan_new_projects(self) -> None:
        """Compare APPS_DIR contents with known set; launch any newcomers."""
        if not APPS_DIR.exists():
            return
        current = {d.name for d in APPS_DIR.iterdir() if d.is_dir()}
        new_ids = current - self._known
        for project_id in sorted(new_ids):
            self._known.add(project_id)
            project_path = APPS_DIR / project_id
            # If already tracked (e.g. launched by CommandAction) and failed,
            # start repair loop instead of blind relaunch.
            entry = get_manager().get(project_id)
            status = entry.get("status") if entry else None

            if status == "failed":
                # Already crashed — jump straight to repair
                logger.info(
                    "🆕 [RE] detected failed project '%s' — starting repair loop",
                    project_id,
                )
                asyncio.create_task(self._repair_loop(project_id, project_path))

            elif status == "running":
                # Running now but may crash later — schedule repair watcher.
                # The repair loop's first action is to wait, then re-check status;
                # if still running it returns immediately (no-op).
                logger.info(
                    "🆕 [RE] project '%s' already running — scheduling repair watcher",
                    project_id,
                )
                asyncio.create_task(self._repair_loop(project_id, project_path))

            else:
                logger.info("🆕 [RE] new project detected: '%s'", project_id)
                launched = await self._launch_project(project_id, project_path)
                if launched:
                    asyncio.create_task(
                        self._repair_loop(project_id, project_path)
                    )

    # ── Repair loop (delegates to RepairEngine) ────────────────────

    async def _repair_loop(
        self,
        project_id: str,
        project_path: Path,
        max_retries: int = MAX_REPAIR_RETRIES,
    ) -> None:
        """
        Background coroutine: delegates crash repair to RepairEngine.
        RepairEngine handles classification, snapshots, pip install, and git
        checkpoints.  This method is kept thin so RuntimeEngine stays focused
        on process lifecycle.
        """
        from core.repair_engine import get_repair_engine
        result = await get_repair_engine().run(
            project_id=project_id,
            project_path=project_path,
            launcher=self._launch_project,
            max_retries=max_retries,
        )
        if result["success"]:
            logger.info("[RE] '%s' repaired successfully", project_id)
        else:
            logger.warning(
                "[RE] '%s' repair exhausted: %s", project_id, result.get("final_error")
            )

    # ── Core launch ────────────────────────────────────────────────

    async def _launch_project(
        self, project_id: str, project_path: Path, *, force: bool = False
    ) -> bool:
        """
        Core launch logic: detect entry-point → allocate port → spawn → register.

        Uses subprocess.Popen (synchronous) + daemon threads for stdout/stderr
        streaming.  This avoids all asyncio event-loop compatibility issues on
        Windows (SelectorEventLoop vs ProactorEventLoop, --reload workers, etc.).
        """
        # Always work with an absolute path so cwd is unambiguous
        project_path = project_path.resolve()

        # ── Guard: already running or previously failed ────────────
        # "failed" projects must be fixed before relaunch; the scanner must
        # never blindly retry a crashed project — that creates an infinite loop.
        # Repair is handled explicitly by _repair_loop().
        entry = get_manager().get(project_id)
        if entry:
            status = entry.get("status")
            if status == "running":
                logger.info("⏭️ [RE] '%s' already running — skip", project_id)
                return False
            if status == "failed" and not force:
                logger.info(
                    "⏭️ [RE] '%s' previously failed — skipping blind relaunch "
                    "(repair loop handles this)",
                    project_id,
                )
                return False

        # ── Guard: path exists ──────────────────────────────────────
        if not project_path.exists():
            logger.warning("⚠️ [RE] project path missing: %s", project_path)
            return False

        # ── Detect files ────────────────────────────────────────────
        # Use rglob so nested layouts like backend/app.py are visible.
        # Paths are stored relative to project_path with forward slashes
        # so get_run_command() can match "backend/app.py" correctly.
        try:
            file_stubs = [
                {"path": f.relative_to(project_path).as_posix()}
                for f in project_path.rglob("*")
                if f.is_file()
            ]
        except OSError as exc:
            logger.warning("⚠️ [RE] cannot list '%s': %s", project_id, exc)
            return False

        # ── Resolve launch command ──────────────────────────────────
        port    = find_free_port()
        command = get_run_command(str(project_path), file_stubs, port=port)

        if not command:
            logger.warning(
                "⚠️ [RE] no entry-point found in '%s' (files: %s)",
                project_id, [s["path"] for s in file_stubs],
            )
            return False

        if not _is_safe_command(command):
            logger.warning("🚫 [RE] command blocked for '%s': %s", project_id, command)
            return False

        # ── Guard: entry-point file exists ──────────────────────────
        # command[3] = "sistema_monitoreo.app:app" → dotted module path
        # Convert to filesystem path and verify it exists before spawning.
        if len(command) > 3 and ":" in command[3]:
            module_name  = command[3].split(":")[0]     # e.g. "sistema_monitoreo.app"
            module_parts = module_name.split(".")        # ["sistema_monitoreo", "app"]
            # Reconstruct path: join all parts and append .py to the last segment
            entry_file = project_path.joinpath(*module_parts[:-1]) / f"{module_parts[-1]}.py"
            if not entry_file.exists():
                logger.error(
                    "❌ [RE] entry-point '%s' missing — abort launch of '%s'",
                    "/".join(module_parts[:-1] + [module_parts[-1] + ".py"]),
                    project_id,
                )
                return False
            logger.info(
                "✅ [RUNTIME] detected %s → launching %s:app",
                entry_file.relative_to(project_path).as_posix(), module_name,
            )

        logger.info(
            "🚀 [RE] launching '%s'\n  cmd : %s\n  cwd : %s\n  port: %s",
            project_id, " ".join(command), project_path, port,
        )

        # ── Spawn via Popen (no asyncio subprocess — Windows-safe) ──
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(project_path),
            )
        except Exception as exc:
            logger.error(
                "❌ [RE] Popen failed for '%s': %s\n  cmd: %s\n  cwd: %s",
                project_id, exc, " ".join(command), project_path,
            )
            return False

        # Pre-register immediately so concurrent launchers (CommandAction) see this
        # entry as "running" during the 500ms startup window and skip a duplicate.
        manager = get_manager()
        manager.register(project_id, proc, command, str(project_path))

        # ── Immediate-crash check (give uvicorn 500 ms to start) ────
        await asyncio.sleep(0.5)
        rc = proc.poll()
        if rc is not None:
            # Process already dead — drain pipes synchronously
            stdout_txt = proc.stdout.read().decode("utf-8", errors="replace").strip()
            stderr_txt = proc.stderr.read().decode("utf-8", errors="replace").strip()
            crash_text = stderr_txt or stdout_txt or f"(no output — rc={rc})"

            # Store crash logs and mark failed (entry already registered above)
            _mgr = get_manager()
            for _line in crash_text.splitlines():
                _mgr.update_log(project_id, _line)
            _mgr.set_status(project_id, "failed")

            logger.error(
                "❌ [RE] '%s' exited immediately (rc=%d)\n"
                "  cmd : %s\n"
                "  cwd : %s\n"
                "--- stderr ---\n%s",
                project_id, rc,
                " ".join(command), project_path,
                crash_text[:500],
            )
            return False

        # ── Start streaming threads (already registered above before sleep) ──

        # Open a per-project log file so the dashboard (separate process)
        # can tail it for live log streaming without IPC.
        log_fh = None
        try:
            log_fh = open(project_path / ".nexus.log", "w", encoding="utf-8", buffering=1)
        except OSError as exc:
            logger.warning("⚠️ [RE] cannot open log file for '%s': %s", project_id, exc)

        for stream, label in [(proc.stdout, "stdout"), (proc.stderr, "stderr")]:
            threading.Thread(
                target=_popen_read_stream,
                args=(stream, project_id, label, log_fh),
                daemon=True,
                name=f"re-{project_id[:8]}-{label}",
            ).start()

        threading.Thread(
            target=_popen_monitor,
            args=(proc, project_id),
            daemon=True,
            name=f"re-{project_id[:8]}-mon",
        ).start()

        logger.info(
            "✅ [RE] '%s' running — pid=%d  port=%s",
            project_id, proc.pid, port,
        )
        return True


# ── Module-level singleton ─────────────────────────────────────────────────

_engine: Optional[RuntimeEngine] = None


def get_engine() -> RuntimeEngine:
    """Return the global RuntimeEngine singleton, creating it if needed."""
    global _engine
    if _engine is None:
        _engine = RuntimeEngine()
    return _engine
