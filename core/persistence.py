"""
Persistent storage for NexusAgentes learning loop state.

Uses SQLite (stdlib sqlite3) for deterministic, fail-safe persistence
of identity patterns, performance state, and adaptive config.

Deterministic — no AI, no randomness, no side effects outside DB.
Fail-safe — never crashes the caller, always returns safe defaults.
"""
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Database file ───────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nexus_state.db")
# Resolve to absolute path
DB_PATH = os.path.normpath(os.path.abspath(DB_PATH))

# ── Thread lock for SQLite (single-writer safety) ───────────────────
_db_lock = threading.Lock()

# ── Default identity structure ──────────────────────────────────────
DEFAULT_IDENTITY: Dict[str, Any] = {
    "user_name": None,
    "project_name": None,
    "goals": [],
    "interests": [],
    "patterns": {},
    "global_patterns": {},
}

# ── Default performance state structure ─────────────────────────────
DEFAULT_PERFORMANCE: Dict[str, Any] = {
    "intent":  {"correct": 0, "total": 0},
    "global":  {"correct": 0, "total": 0},
    "conflict": {"correct": 0, "total": 0},
}

# ── Default config structure ────────────────────────────────────────
DEFAULT_CONFIG: Dict[str, Any] = {
    "dominance_threshold": 1.5,
    "intent_weight_factor": 0.5,
    "global_weight_factor": 0.5,
}

# ── Connection cache for in-memory DB support ───────────────────────
_connection_cache: Dict[str, sqlite3.Connection] = {}


def _get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with auto-created tables."""
    if DB_PATH in _connection_cache:
        conn = _connection_cache[DB_PATH]
        # Verify connection is still alive
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            del _connection_cache[DB_PATH]

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_tables(conn)
    _connection_cache[DB_PATH] = conn
    return conn


def _close_connection() -> None:
    """Close cached connection (for testing)."""
    if DB_PATH in _connection_cache:
        try:
            _connection_cache[DB_PATH].close()
        except Exception:
            pass
        del _connection_cache[DB_PATH]


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS identity_patterns (
            user_id TEXT PRIMARY KEY,
            patterns_json TEXT NOT NULL,
            global_patterns_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS performance_state (
            user_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('intent','global','conflict')),
            correct INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, source)
        );

        CREATE TABLE IF NOT EXISTS adaptive_config (
            user_id TEXT PRIMARY KEY,
            dominance_threshold REAL NOT NULL DEFAULT 1.5,
            intent_weight_factor REAL NOT NULL DEFAULT 0.5,
            global_weight_factor REAL NOT NULL DEFAULT 0.5,
            previous_accuracy_json TEXT,
            updated_at TEXT NOT NULL
        );
    """)


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════

def _safe_json_serialize(obj: Any) -> str:
    """Safely serialize an object to JSON; return '{}' on failure."""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError, OverflowError) as e:
        logger.warning("JSON serialization failed: %s", e)
        return "{}"


def _safe_json_deserialize(text: Any) -> Any:
    """Safely deserialize a JSON string; return None on failure."""
    if not isinstance(text, str):
        return None
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("JSON deserialization failed: %s", e)
        return None


def _utc_now() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _validate_user_id(user_id: Any) -> str:
    """Validate and normalize user_id to string."""
    if not isinstance(user_id, str):
        user_id = str(user_id) if user_id is not None else "default"
    if not user_id.strip():
        user_id = "default"
    return user_id.strip()


# ═══════════════════════════════════════════════════════════════════
# Identity persistence
# ═══════════════════════════════════════════════════════════════════

def load_identity(user_id: str) -> Dict[str, Any]:
    """
    Load identity patterns from the database.

    Args:
        user_id: The user identifier (string).

    Returns:
        dict with keys: user_name, project_name, goals, interests,
        patterns, global_patterns. Returns DEFAULT_IDENTITY if missing.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(user_id, str):
        return dict(DEFAULT_IDENTITY)

    try:
        with _db_lock:
            conn = _get_connection()
            cursor = conn.execute(
                "SELECT patterns_json, global_patterns_json "
                "FROM identity_patterns WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return dict(DEFAULT_IDENTITY)

        patterns = _safe_json_deserialize(row["patterns_json"])
        global_patterns = _safe_json_deserialize(row["global_patterns_json"])

        identity = dict(DEFAULT_IDENTITY)
        if isinstance(patterns, dict):
            identity["patterns"] = patterns
        if isinstance(global_patterns, dict):
            identity["global_patterns"] = global_patterns

        return identity

    except sqlite3.Error as e:
        logger.error("SQLite error in load_identity: %s", e, exc_info=True)
        return dict(DEFAULT_IDENTITY)
    except Exception as e:
        logger.error("Unexpected error in load_identity: %s", e, exc_info=True)
        return dict(DEFAULT_IDENTITY)


def save_identity(user_id: str, identity: Dict[str, Any]) -> None:
    """
    Save identity patterns to the database.

    Args:
        user_id:   The user identifier (string).
        identity:  Dict with at least "patterns" and "global_patterns" keys.

    This function never raises. Failures are logged and silently dropped.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(identity, dict):
        logger.warning("save_identity: identity is not a dict, skipping")
        return

    patterns = identity.get("patterns", {})
    global_patterns = identity.get("global_patterns", {})

    if not isinstance(patterns, dict):
        patterns = {}
    if not isinstance(global_patterns, dict):
        global_patterns = {}

    patterns_json = _safe_json_serialize(patterns)
    global_patterns_json = _safe_json_serialize(global_patterns)
    updated_at = _utc_now()

    try:
        with _db_lock:
            conn = _get_connection()
            conn.execute(
                """INSERT OR REPLACE INTO identity_patterns
                   (user_id, patterns_json, global_patterns_json, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, patterns_json, global_patterns_json, updated_at),
            )
            conn.commit()
        logger.debug("Identity saved for user '%s'", user_id)
    except sqlite3.Error as e:
        logger.error("SQLite error in save_identity: %s", e, exc_info=True)
    except Exception as e:
        logger.error("Unexpected error in save_identity: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# Performance state persistence
# ═══════════════════════════════════════════════════════════════════

def load_performance(user_id: str) -> Dict[str, Any]:
    """
    Load performance tracking state from the database.

    Args:
        user_id: The user identifier (string).

    Returns:
        dict with keys "intent", "global", "conflict" each containing
        {"correct": int, "total": int}. Returns DEFAULT_PERFORMANCE if missing.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(user_id, str):
        return _deep_copy_perf(DEFAULT_PERFORMANCE)

    try:
        with _db_lock:
            conn = _get_connection()
            cursor = conn.execute(
                "SELECT source, correct, total "
                "FROM performance_state WHERE user_id = ?",
                (user_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return _deep_copy_perf(DEFAULT_PERFORMANCE)

        state: Dict[str, Any] = {}
        for row in rows:
            source = str(row["source"])
            correct = row["correct"]
            total = row["total"]

            if not isinstance(correct, int):
                correct = 0
            if not isinstance(total, int):
                total = 0

            state[source] = {"correct": correct, "total": total}

        # Ensure all three sources exist
        for source in ("intent", "global", "conflict"):
            if source not in state:
                state[source] = {"correct": 0, "total": 0}

        return state

    except sqlite3.Error as e:
        logger.error("SQLite error in load_performance: %s", e, exc_info=True)
        return _deep_copy_perf(DEFAULT_PERFORMANCE)
    except Exception as e:
        logger.error("Unexpected error in load_performance: %s", e, exc_info=True)
        return _deep_copy_perf(DEFAULT_PERFORMANCE)


def save_performance(user_id: str, state: Dict[str, Any]) -> None:
    """
    Save performance tracking state to the database.

    Args:
        user_id: The user identifier (string).
        state:   Dict with keys "intent", "global", "conflict" each
                 containing {"correct": int, "total": int}.

    This function never raises. Failures are logged and silently dropped.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(state, dict):
        logger.warning("save_performance: state is not a dict, skipping")
        return

    TRACKED_SOURCES = ("intent", "global", "conflict")

    try:
        with _db_lock:
            conn = _get_connection()
            for source in TRACKED_SOURCES:
                entry = state.get(source)
                if not isinstance(entry, dict):
                    continue

                correct = entry.get("correct", 0)
                total = entry.get("total", 0)

                if not isinstance(correct, int):
                    correct = 0
                if not isinstance(total, int):
                    total = 0

                conn.execute(
                    """INSERT OR REPLACE INTO performance_state
                       (user_id, source, correct, total)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, source, correct, total),
                )
            conn.commit()
        logger.debug("Performance state saved for user '%s'", user_id)
    except sqlite3.Error as e:
        logger.error("SQLite error in save_performance: %s", e, exc_info=True)
    except Exception as e:
        logger.error("Unexpected error in save_performance: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# Config persistence
# ═══════════════════════════════════════════════════════════════════

def load_config(user_id: str) -> Dict[str, Any]:
    """
    Load adaptive config from the database.

    Args:
        user_id: The user identifier (string).

    Returns:
        dict with keys: dominance_threshold, intent_weight_factor,
        global_weight_factor, previous_accuracy. Returns DEFAULT_CONFIG
        if missing.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(user_id, str):
        return dict(DEFAULT_CONFIG)

    try:
        with _db_lock:
            conn = _get_connection()
            cursor = conn.execute(
                """SELECT dominance_threshold, intent_weight_factor,
                          global_weight_factor, previous_accuracy_json
                   FROM adaptive_config WHERE user_id = ?""",
                (user_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return dict(DEFAULT_CONFIG)

        config = dict(DEFAULT_CONFIG)
        config["dominance_threshold"] = float(row["dominance_threshold"])
        config["intent_weight_factor"] = float(row["intent_weight_factor"])
        config["global_weight_factor"] = float(row["global_weight_factor"])

        prev_acc = _safe_json_deserialize(row["previous_accuracy_json"])
        if isinstance(prev_acc, dict):
            config["previous_accuracy"] = prev_acc

        return config

    except sqlite3.Error as e:
        logger.error("SQLite error in load_config: %s", e, exc_info=True)
        return dict(DEFAULT_CONFIG)
    except Exception as e:
        logger.error("Unexpected error in load_config: %s", e, exc_info=True)
        return dict(DEFAULT_CONFIG)


def save_config(user_id: str, config: Dict[str, Any]) -> None:
    """
    Save adaptive config to the database.

    Args:
        user_id: The user identifier (string).
        config:  Dict with optional keys: dominance_threshold,
                 intent_weight_factor, global_weight_factor,
                 previous_accuracy (dict).

    This function never raises. Failures are logged and silently dropped.
    """
    user_id = _validate_user_id(user_id)

    if not isinstance(config, dict):
        logger.warning("save_config: config is not a dict, skipping")
        return

    dominance = config.get("dominance_threshold", 1.5)
    intent_w = config.get("intent_weight_factor", 0.5)
    global_w = config.get("global_weight_factor", 0.5)

    if not isinstance(dominance, (int, float)):
        dominance = 1.5
    if not isinstance(intent_w, (int, float)):
        intent_w = 0.5
    if not isinstance(global_w, (int, float)):
        global_w = 0.5

    previous_accuracy = config.get("previous_accuracy")
    previous_accuracy_json: Optional[str] = None
    if isinstance(previous_accuracy, dict):
        previous_accuracy_json = _safe_json_serialize(previous_accuracy)

    updated_at = _utc_now()

    try:
        with _db_lock:
            conn = _get_connection()
            conn.execute(
                """INSERT OR REPLACE INTO adaptive_config
                   (user_id, dominance_threshold, intent_weight_factor,
                    global_weight_factor, previous_accuracy_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, float(dominance), float(intent_w),
                 float(global_w), previous_accuracy_json, updated_at),
            )
            conn.commit()
        logger.debug("Config saved for user '%s'", user_id)
    except sqlite3.Error as e:
        logger.error("SQLite error in save_config: %s", e, exc_info=True)
    except Exception as e:
        logger.error("Unexpected error in save_config: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════

def _deep_copy_perf(perf: Dict[str, Any]) -> Dict[str, Any]:
    """Create a deep copy of a performance dict."""
    return {
        src: {"correct": data["correct"], "total": data["total"]}
        for src, data in perf.items()
    }
