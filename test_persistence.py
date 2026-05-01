"""
Tests for core/persistence.py — Learning loop state persistence.

Test cases:
1. save + load identity
2. save + load performance
3. save + load config
4. missing user returns defaults
5. corrupted data handled safely
6. determinism
"""
import os
import sys
import tempfile
import unittest

# Create a temp directory for DB to not interfere with production
_test_dir = tempfile.mkdtemp(prefix="nexus_test_")
_test_db = os.path.join(_test_dir, "test_nexus_state.db")

import core.persistence as persistence

# Override DB_PATH before any function is called
persistence.DB_PATH = _test_db

# Ensure clean start
if os.path.exists(_test_db):
    os.remove(_test_db)
persistence._close_connection()

from core.persistence import (
    load_identity,
    save_identity,
    load_performance,
    save_performance,
    load_config,
    save_config,
    DEFAULT_IDENTITY,
    DEFAULT_PERFORMANCE,
    DEFAULT_CONFIG,
)


def _clean_db():
    """Remove the test DB and close cached connection."""
    persistence._close_connection()
    if os.path.exists(_test_db):
        try:
            os.remove(_test_db)
        except PermissionError:
            pass


class TestPersistenceIdentity(unittest.TestCase):
    """Tests for identity pattern persistence."""

    def setUp(self):
        self.user_id = "test_user_identity"

    def tearDown(self):
        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute("DELETE FROM identity_patterns WHERE user_id = ?", (self.user_id,))
        conn.commit()

    @classmethod
    def tearDownClass(cls):
        _clean_db()

    def test_save_and_load_identity(self):
        identity = {
            "patterns": {
                "tone": {"greeting": {"formal": 2.5, "casual": 1.0}},
            },
            "global_patterns": {
                "tone": {"formal": 3.5, "casual": 1.0},
            },
        }
        save_identity(self.user_id, identity)
        loaded = load_identity(self.user_id)
        self.assertIsInstance(loaded, dict)
        self.assertEqual(loaded["patterns"], identity["patterns"])
        self.assertEqual(loaded["global_patterns"], identity["global_patterns"])

    def test_missing_user_returns_default_identity(self):
        loaded = load_identity("nonexistent_user_xyz")
        self.assertEqual(loaded["patterns"], DEFAULT_IDENTITY["patterns"])
        self.assertEqual(loaded["global_patterns"], DEFAULT_IDENTITY["global_patterns"])

    def test_empty_user_id_defaults(self):
        loaded = load_identity("")
        self.assertEqual(loaded["patterns"], {})

    def test_save_non_dict_identity_does_not_crash(self):
        save_identity(self.user_id, "invalid")
        loaded = load_identity(self.user_id)
        self.assertEqual(loaded["patterns"], {})

    def test_identity_determinism(self):
        identity = {
            "patterns": {"tone": {"hi": {"formal": 1.0}}},
            "global_patterns": {"tone": {"formal": 1.0}},
        }
        save_identity(self.user_id, identity)
        loaded1 = load_identity(self.user_id)
        # Save again same data
        save_identity(self.user_id, identity)
        loaded2 = load_identity(self.user_id)
        self.assertEqual(loaded1["patterns"], loaded2["patterns"])


class TestPersistencePerformance(unittest.TestCase):
    """Tests for performance state persistence."""

    def setUp(self):
        self.user_id = "test_user_perf"

    def tearDown(self):
        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute("DELETE FROM performance_state WHERE user_id = ?", (self.user_id,))
        conn.commit()

    @classmethod
    def tearDownClass(cls):
        _clean_db()

    def test_save_and_load_performance(self):
        state = {
            "intent": {"correct": 8, "total": 10},
            "global": {"correct": 3, "total": 5},
            "conflict": {"correct": 7, "total": 9},
        }
        save_performance(self.user_id, state)
        loaded = load_performance(self.user_id)
        self.assertEqual(loaded, state)

    def test_missing_user_returns_default_performance(self):
        loaded = load_performance("nonexistent_user_perf")
        self.assertEqual(loaded["intent"], DEFAULT_PERFORMANCE["intent"])
        self.assertEqual(loaded["global"], DEFAULT_PERFORMANCE["global"])
        self.assertEqual(loaded["conflict"], DEFAULT_PERFORMANCE["conflict"])

    def test_partial_state_supplements_defaults(self):
        partial = {"intent": {"correct": 5, "total": 5}}
        save_performance(self.user_id, partial)
        loaded = load_performance(self.user_id)
        self.assertEqual(loaded["intent"], {"correct": 5, "total": 5})
        self.assertEqual(loaded["global"], {"correct": 0, "total": 0})
        self.assertEqual(loaded["conflict"], {"correct": 0, "total": 0})


class TestPersistenceConfig(unittest.TestCase):
    """Tests for adaptive config persistence."""

    def setUp(self):
        self.user_id = "test_user_config"

    def tearDown(self):
        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute("DELETE FROM adaptive_config WHERE user_id = ?", (self.user_id,))
        conn.commit()

    @classmethod
    def tearDownClass(cls):
        _clean_db()

    def test_save_and_load_config(self):
        config = {
            "dominance_threshold": 1.3,
            "intent_weight_factor": 0.7,
            "global_weight_factor": 0.3,
            "previous_accuracy": {"intent": 0.8, "global": 0.4},
        }
        save_config(self.user_id, config)
        loaded = load_config(self.user_id)
        self.assertAlmostEqual(loaded["dominance_threshold"], 1.3)
        self.assertAlmostEqual(loaded["intent_weight_factor"], 0.7)
        self.assertAlmostEqual(loaded["global_weight_factor"], 0.3)
        self.assertEqual(loaded["previous_accuracy"], {"intent": 0.8, "global": 0.4})

    def test_missing_user_returns_default_config(self):
        loaded = load_config("nonexistent_user_cfg")
        self.assertAlmostEqual(loaded["dominance_threshold"],
                                DEFAULT_CONFIG["dominance_threshold"])

    def test_invalid_types_clamped_to_defaults(self):
        bad_config = {
            "dominance_threshold": "not_a_number",
            "intent_weight_factor": [1, 2, 3],
            "global_weight_factor": None,
        }
        save_config(self.user_id, bad_config)
        loaded = load_config(self.user_id)
        self.assertAlmostEqual(loaded["dominance_threshold"],
                                DEFAULT_CONFIG["dominance_threshold"])

    def test_config_determinism(self):
        config = {"dominance_threshold": 2.0, "intent_weight_factor": 1.0, "global_weight_factor": 0.1}
        save_config(self.user_id, config)
        loaded1 = load_config(self.user_id)
        save_config(self.user_id, config)
        loaded2 = load_config(self.user_id)
        self.assertEqual(loaded1["dominance_threshold"], loaded2["dominance_threshold"])


class TestPersistenceSafety(unittest.TestCase):
    """Tests for safety and edge cases."""

    @classmethod
    def tearDownClass(cls):
        _clean_db()

    def test_full_roundtrip(self):
        user_id = "roundtrip_user"
        identity = {"patterns": {"tone": {"hi": {"warm": 3.0}}}, "global_patterns": {"tone": {"warm": 3.0}}}
        perf = {"intent": {"correct": 10, "total": 20}, "global": {"correct": 5, "total": 20}, "conflict": {"correct": 15, "total": 20}}
        cfg = {"dominance_threshold": 1.7, "intent_weight_factor": 0.6, "global_weight_factor": 0.4}

        save_identity(user_id, identity)
        save_performance(user_id, perf)
        save_config(user_id, cfg)

        loaded_id = load_identity(user_id)
        loaded_perf = load_performance(user_id)
        loaded_cfg = load_config(user_id)

        self.assertEqual(loaded_id["patterns"], identity["patterns"])
        self.assertEqual(loaded_perf, perf)
        self.assertAlmostEqual(loaded_cfg["dominance_threshold"], 1.7)

        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute("DELETE FROM identity_patterns WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM performance_state WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM adaptive_config WHERE user_id = ?", (user_id,))
        conn.commit()

    def test_save_never_raises(self):
        try:
            save_identity(None, None)
            save_performance(None, None)
            save_config(None, None)
            save_identity("", {})
            save_performance("", {})
            save_config("", {})
        except Exception:
            self.fail("save_* raised an exception")

    def test_load_never_raises(self):
        try:
            load_identity(None)
            load_performance(None)
            load_config(None)
            load_identity("")
            load_performance({})
        except Exception:
            self.fail("load_* raised an exception")

    def test_corrupted_json_returns_defaults(self):
        user_id = "corrupted_user"
        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO identity_patterns "
            "(user_id, patterns_json, global_patterns_json, updated_at) "
            "VALUES (?, '{bad json', '{also bad}', '2024-01-01')",
            (user_id,),
        )
        conn.commit()

        loaded = load_identity(user_id)
        self.assertEqual(loaded["patterns"], {})

        conn = persistence._get_connection()
        conn.execute("DELETE FROM identity_patterns WHERE user_id = ?", (user_id,))
        conn.commit()

    def test_multiple_users_isolated(self):
        save_identity("user_a", {"patterns": {"tone": {"hi": {"a": 1.0}}}, "global_patterns": {"tone": {"a": 1.0}}})
        save_identity("user_b", {"patterns": {"tone": {"hi": {"b": 2.0}}}, "global_patterns": {"tone": {"b": 2.0}}})
        self.assertEqual(load_identity("user_a")["patterns"]["tone"]["hi"], {"a": 1.0})
        self.assertEqual(load_identity("user_b")["patterns"]["tone"]["hi"], {"b": 2.0})

        persistence._close_connection()
        conn = persistence._get_connection()
        conn.execute("DELETE FROM identity_patterns WHERE user_id IN ('user_a', 'user_b')")
        conn.commit()


class TestPersistenceDeterminism(unittest.TestCase):
    """Verify determinism."""

    @classmethod
    def tearDownClass(cls):
        _clean_db()

    def test_deterministic_identity_default(self):
        r1 = load_identity("det_test_1")
        r2 = load_identity("det_test_1")
        self.assertEqual(r1, r2)

    def test_deterministic_performance_default(self):
        r1 = load_performance("det_test_2")
        r2 = load_performance("det_test_2")
        self.assertEqual(r1, r2)

    def test_deterministic_config_default(self):
        r1 = load_config("det_test_3")
        r2 = load_config("det_test_3")
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    # Clean up temp dir
    _clean_db()
    try:
        os.rmdir(_test_dir)
    except OSError:
        pass
    sys.exit(0 if result.result.wasSuccessful() else 1)
