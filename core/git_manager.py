"""
core/git_manager.py
===================
Auto git checkpoints for generated project directories.

Every important change (generation, successful repair, validation pass) is
committed so the entire history is recoverable with `git log`.

NEVER crashes Nexus — every operation is wrapped in try/except.
"""
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_GIT_AUTHOR = "Nexus <nexus@local>"
_GIT_TIMEOUT = 30  # seconds per git subprocess


def _run(args: list, cwd: Path) -> subprocess.CompletedProcess:
    """Execute a git sub-command and return the CompletedProcess."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


def ensure_git_repo(project_path: Path) -> bool:
    """
    Ensure *project_path* is a git repository.
    Runs `git init` if .git does not exist.
    Returns True when the repo is ready.
    """
    try:
        git_dir = project_path / ".git"
        if not git_dir.exists():
            r = _run(["init"], project_path)
            if r.returncode != 0:
                logger.warning(
                    "[GIT] init failed in %s: %s", project_path, r.stderr.strip()
                )
                return False
            # Set a local identity so commits never fail on bare systems
            _run(["config", "user.email", "nexus@local"], project_path)
            _run(["config", "user.name", "Nexus"], project_path)
            logger.info("[GIT] initialized repo in %s", project_path.name)
        return True
    except Exception as exc:
        logger.warning("[GIT] ensure_git_repo error: %s", exc)
        return False


def checkpoint(project_path: Path, message: str) -> bool:
    """
    Stage all changes and create a git commit with *message*.

    Returns True on success (including the no-changes case).
    Returns False only when git itself errors — never raises.
    """
    try:
        if not ensure_git_repo(project_path):
            return False

        # Stage everything
        r = _run(["add", "-A"], project_path)
        if r.returncode != 0:
            logger.warning("[GIT] add -A failed in %s: %s", project_path.name, r.stderr.strip())
            return False

        # Nothing staged → clean tree, not an error
        r = _run(["diff", "--cached", "--quiet"], project_path)
        if r.returncode == 0:
            logger.debug("[GIT] nothing to commit in %s", project_path.name)
            return True

        r = _run(
            ["commit", "-m", message, f"--author={_GIT_AUTHOR}"],
            project_path,
        )
        if r.returncode != 0:
            logger.warning(
                "[GIT] commit failed in %s: %s", project_path.name, r.stderr.strip()
            )
            return False

        logger.info("[GIT] checkpoint '%s' → %s", project_path.name, message)
        return True

    except Exception as exc:
        logger.warning("[GIT] checkpoint error: %s", exc)
        return False


def latest_commit(project_path: Path) -> str:
    """Return the short hash of the latest commit, or '' if unavailable."""
    try:
        r = _run(["rev-parse", "--short", "HEAD"], project_path)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
