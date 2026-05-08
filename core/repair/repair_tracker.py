"""
core/repair/repair_tracker.py
==============================
Persists repair attempts and outcomes to SQLite.
Exposes metrics: repair_success_rate, repair_failures, repair_attempts.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_DB_PATH = Path("repair_history.db").resolve()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    try:
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repair_attempts (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id     TEXT    NOT NULL,
                    attempt        INTEGER NOT NULL,
                    error_category TEXT    NOT NULL,
                    error_detail   TEXT    DEFAULT '',
                    fix_applied    TEXT    DEFAULT '',
                    success        INTEGER NOT NULL DEFAULT 0,
                    timestamp      REAL    NOT NULL
                )
            """)
            conn.commit()
    except Exception as exc:
        logger.warning("[TRACKER] init_db failed: %s", exc)


_init_db()


def record_attempt(
    project_id: str,
    attempt: int,
    error_category: str,
    error_detail: str = "",
    fix_applied: str = "",
    success: bool = False,
) -> None:
    """Persist one repair attempt to the database."""
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO repair_attempts
                       (project_id, attempt, error_category, error_detail, fix_applied, success, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    attempt,
                    error_category,
                    (error_detail or "")[:500],
                    fix_applied or "",
                    int(success),
                    time.time(),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("[TRACKER] record_attempt failed: %s", exc)


def get_metrics() -> Dict:
    """Return aggregate repair metrics."""
    try:
        with _get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)       AS total,
                    SUM(success)   AS successes,
                    COUNT(*) - SUM(success) AS failures
                FROM repair_attempts
            """).fetchone()
            total     = row["total"]     or 0
            successes = row["successes"] or 0
            failures  = row["failures"]  or 0
            rate      = round(successes / total * 100, 1) if total else 0.0
            return {
                "repair_attempts":     total,
                "repair_successes":    successes,
                "repair_failures":     failures,
                "repair_success_rate": rate,
            }
    except Exception as exc:
        logger.warning("[TRACKER] get_metrics failed: %s", exc)
        return {"repair_attempts": 0, "repair_successes": 0, "repair_failures": 0, "repair_success_rate": 0.0}


def get_history(limit: int = 50) -> List[Dict]:
    """Return the most recent repair attempts, newest first."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM repair_attempts ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[TRACKER] get_history failed: %s", exc)
        return []


def get_project_history(project_id: str) -> List[Dict]:
    """Return all repair attempts for a specific project."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM repair_attempts WHERE project_id=? ORDER BY timestamp DESC",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[TRACKER] get_project_history failed: %s", exc)
        return []
