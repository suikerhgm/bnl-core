# core/actions/command_action.py

import asyncio
import os
import re
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.actions.base_action import BaseAction
from core.runtime.process_manager import get_manager, extract_port

logger = logging.getLogger(__name__)


# ── Python-executable detection ────────────────────────────────────────────

def get_python_executable() -> str:
    """
    Return the Python interpreter that should be used to spawn uvicorn.

    Resolution order:
    1. Already inside a venv  → sys.executable is already the venv python.
    2. A venv/ or .venv/ next to the project root → use its python.
    3. Fallback → sys.executable (system python, best-effort).

    Using ``python -m uvicorn`` instead of the bare ``uvicorn`` binary is
    the only reliable way to guarantee the correct site-packages are used on
    Windows virtualenvs, where the Scripts/ directory may not be on PATH.
    """
    # Already running inside a venv
    if sys.prefix != sys.base_prefix:
        return sys.executable

    # Walk up from this file to find the project root, then look for a venv
    project_root = Path(__file__).resolve().parent.parent.parent
    scripts_dir = "Scripts" if sys.platform == "win32" else "bin"
    python_name = "python.exe" if sys.platform == "win32" else "python"

    for venv_name in ("venv", ".venv", "env", ".env"):
        candidate = project_root / venv_name / scripts_dir / python_name
        if candidate.exists():
            logger.debug("🐍 [CMD] venv python found: %s", candidate)
            return str(candidate)

    logger.warning(
        "⚠️ [CMD] no venv found under %s — falling back to %s",
        project_root, sys.executable,
    )
    return sys.executable


# ── Whitelist ──────────────────────────────────────────────────────────────
# Static entries kept for legacy / npm commands.  All uvicorn variants are
# now validated dynamically by _is_safe_command so the Python path doesn't
# need to be hard-coded here.

SAFE_COMMANDS: List[List[str]] = [
    ["npm", "install"],
    ["npm", "start"],
    ["npm", "run", "dev"],
]

_SAFE_SET: frozenset = frozenset(tuple(c) for c in SAFE_COMMANDS)


def get_run_command(
    project_path: str,
    files: list,
    port: Optional[int] = None,
) -> Optional[List[str]]:
    """
    Detect the appropriate run command for a generated project.

    Uses EntrypointDetector as the single source of truth for Python projects.
    All manual path-to-module guessing has been removed — the detector reads
    actual file content and constructs the correct dotted module path regardless
    of nesting depth (e.g. sistema_monitoreo/backend/app.py → sistema_monitoreo.backend.app).

    Args:
        project_path: Absolute path to the project directory.
        files:        List of {path} dicts (used only for npm detection).
        port:         TCP port to pass via --port, or None.

    Returns:
        Token list ready for asyncio.create_subprocess_exec, or None.
    """
    python    = get_python_executable()
    port_args = ["--port", str(port)] if port else []

    # npm projects — detected via file list (files may not be on disk yet)
    if any("package.json" in f.get("path", "") for f in files):
        return ["npm", "start"]

    # Python: delegate entirely to EntrypointDetector.
    # The detector scans the actual filesystem so it always reflects reality.
    try:
        from core.runtime.entrypoint_detector import detect_entrypoint
        info = detect_entrypoint(Path(project_path))
        if info:
            rel = info.file_path.relative_to(Path(project_path)).as_posix()
            logger.info(
                "[RUNTIME] detected %s → launching %s:%s",
                rel, info.module_path, info.app_variable,
            )
            return [
                python, "-m", "uvicorn",
                f"{info.module_path}:{info.app_variable}",
            ] + port_args
    except Exception as _exc:
        logger.warning("[RUNTIME] entrypoint_detector error: %s", _exc)

    return None


def _is_safe_command(command: List[str]) -> bool:
    """
    Return True if the command is safe to execute.

    Accepts:
    - Exact matches against SAFE_COMMANDS (npm etc.).
    - ``<python> -m uvicorn <module>:app [--port N] [--host H]``
      where <python> is any interpreter path ending in python / python.exe /
      python3, <module> is one of the known safe modules, and port is in the
      valid unprivileged range (1024–65535).

    ``--reload`` is intentionally NOT accepted: auto-loop modifies generated
    files at runtime and StatReload would race with RuntimeEngine's own
    restart logic, causing reentrant-call crashes.
    """
    if tuple(command) in _SAFE_SET:
        return True

    # python -m uvicorn <module:app> [--reload] [--port N]
    if len(command) >= 4:
        exe = Path(command[0]).name.lower().rstrip(".exe")  # "python" or "python3"
        if exe in ("python", "python3") and command[1] == "-m" and command[2] == "uvicorn":
            module_app = command[3]  # e.g. "backend:app"
            parts = module_app.split(":")
            # Accept any valid dotted Python module path (e.g. sistema_monitoreo.app)
            # rather than a hardcoded whitelist — the module must be a chain of
            # valid Python identifiers and the app variable must also be an identifier.
            module_parts = parts[0].split(".") if len(parts) == 2 else []
            if (
                len(parts) == 2
                and module_parts
                and all(p.isidentifier() for p in module_parts)
                and parts[1].isidentifier()
            ):
                return _valid_uvicorn_flags(command[4:])

    # curl to localhost only — safe for testing generated apps (Bug #1 fix)
    if len(command) >= 2 and command[0] == "curl":
        url = command[-1]
        if re.match(r"https?://(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$", url):
            return True

    return False


def _valid_uvicorn_flags(flags: List[str]) -> bool:
    """
    Return True if every flag in the tail is a known-safe uvicorn option.

    ``--reload`` is explicitly rejected: it lets uvicorn's StatReload watch the
    filesystem and auto-restart on any .py change, which races with
    RuntimeEngine's controlled restarts during auto-loop fix cycles.
    """
    i = 0
    while i < len(flags):
        flag = flags[i]
        if flag == "--reload":
            logger.warning(
                "🚫 [CMD] --reload rejected: use RuntimeEngine for restarts"
            )
            return False
        elif flag == "--port":
            if i + 1 >= len(flags):
                return False
            val = flags[i + 1]
            if not val.isdigit() or not (1024 <= int(val) <= 65535):
                return False
            i += 2
        elif flag == "--host":
            if i + 1 >= len(flags):
                return False
            i += 2  # any host value is fine; network binding is already sandboxed
        else:
            return False
    return True


async def _drain_one(stream: asyncio.StreamReader, project_id: str) -> None:
    """Read a single stream and feed lines into ProcessManager."""
    manager = get_manager()
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            manager.update_log(project_id, decoded)
            port = extract_port(decoded)
            if port:
                manager.set_port(project_id, port)
    except Exception as exc:
        logger.warning("⚠️ [CMD] stream error for '%s': %s", project_id, exc)


async def _stream_output(
    project_id: str,
    process: asyncio.subprocess.Process,
) -> None:
    """Drain stdout + stderr concurrently; update status when process exits."""
    await asyncio.gather(
        _drain_one(process.stdout, project_id),
        _drain_one(process.stderr, project_id),
    )
    await process.wait()
    rc = process.returncode
    final_status = "stopped" if rc in (0, -15) else "failed"
    get_manager().set_status(project_id, final_status)
    logger.info("📋 [CMD] '%s' exited rc=%s → %s", project_id, rc, final_status)


class CommandAction(BaseAction):
    """
    Executor de comandos del sistema (whitelist-only, no-shell, sandboxed).

    Modes:
    - Streaming (project_id provided): spawns process via exec (no shell),
      registers with ProcessManager, streams stdout in background, returns immediately.
    - Legacy (no project_id): communicate() with 15s timeout, returns stdout/stderr.

    command param must be a List[str] matching an entry in SAFE_COMMANDS exactly.
    """

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        self.operation = context.get("operation")
        self.params = context.get("params", {})

    async def execute(self) -> Dict[str, Any]:
        if self.operation != "run":
            logger.warning("⚠️ CommandAction: unsupported operation '%s'", self.operation)
            return {
                "success": False,
                "result": None,
                "error": f"Unsupported operation: {self.operation}",
            }

        command: Optional[List[str]] = self.params.get("command")
        cwd: Optional[str] = self.params.get("cwd")
        project_id: Optional[str] = self.params.get("project_id")

        # ── Validate type ────────────────────────────────────────────────
        if not command or not isinstance(command, list):
            return {"success": False, "result": None, "error": "command must be a non-empty list"}

        if not all(isinstance(t, str) for t in command):
            return {"success": False, "result": None, "error": "command tokens must all be strings"}

        # ── Whitelist check (exact match, no shell) ──────────────────────
        if not _is_safe_command(command):
            logger.warning("🚫 CommandAction: blocked command %s", command)
            return {
                "success": False,
                "result": None,
                "error": f"Command not in whitelist: {command}",
            }

        if cwd and not os.path.isdir(cwd):
            return {
                "success": False,
                "result": None,
                "error": f"Working directory not found: {cwd}",
            }

        cmd_str = " ".join(command)
        logger.info("🚀 CommandAction.run: %s in '%s'", command, cwd)

        # ── Streaming mode (project_id present) ─────────────────────────
        if project_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,   # separate so errors are visible
                    cwd=cwd,
                )
            except Exception as exc:
                logger.error(
                    "❌ [CMD] failed to spawn '%s': %s\n  cmd=%s\n  cwd=%s",
                    project_id, exc, command, cwd,
                )
                return {"success": False, "result": None, "error": str(exc)}

            # Pre-register immediately so RuntimeEngine's scan (which runs every 3s
            # and yields during our 500ms startup check) sees this entry as "running"
            # and skips launching a duplicate process on the same port.
            manager = get_manager()
            manager.register(project_id, proc, command, cwd or "")

            # Brief check — if the process dies within 500 ms it's a startup crash
            await asyncio.sleep(0.5)
            if proc.returncode is not None:
                stdout_b = await proc.stdout.read()
                stderr_b = await proc.stderr.read()
                msg = (
                    f"Process exited immediately (rc={proc.returncode})\n"
                    f"--- stderr ---\n"
                    f"{stderr_b.decode('utf-8', errors='replace').strip() or '(empty)'}\n"
                    f"--- stdout ---\n"
                    f"{stdout_b.decode('utf-8', errors='replace').strip() or '(empty)'}"
                )
                logger.error("❌ [CMD] '%s' crashed on startup:\n%s", project_id, msg)
                manager.set_status(project_id, "failed")
                return {"success": False, "result": None, "error": msg}

            asyncio.create_task(_stream_output(project_id, proc))
            logger.info(
                "✅ [CMD] '%s' running — pid=%d cmd=%s",
                project_id, proc.pid, cmd_str,
            )
            return {
                "success": True,
                "result": {
                    "command": command,
                    "command_str": cmd_str,
                    "project_id": project_id,
                    "mode": "streaming",
                    "pid": proc.pid,
                },
            }

        # ── Legacy communicate() mode (no project_id) ───────────────────
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            timed_out = False
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                timed_out = True
                logger.info("⏱️ CommandAction: timeout after 15s — %s", command)

            return {
                "success": True,
                "result": {
                    "command": command,
                    "command_str": cmd_str,
                    "stdout": stdout.decode("utf-8", errors="replace").strip(),
                    "stderr": stderr.decode("utf-8", errors="replace").strip(),
                    "returncode": proc.returncode,
                    "timed_out": timed_out,
                },
            }

        except Exception as exc:
            logger.error("❌ CommandAction.execute failed: %s", exc, exc_info=True)
            return {"success": False, "result": None, "error": str(exc)}

    def requires_approval(self) -> bool:
        return self.operation == "sudo"

    def get_description(self) -> str:
        command = self.params.get("command", [])
        display = " ".join(command) if isinstance(command, list) else str(command)
        return f"Run: {display}"
