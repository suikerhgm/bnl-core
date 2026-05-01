"""
Test MemoryStabilityGuardLayer.

Validates:
- Rule 1: Minimum data (total >= 5 per source)
- Rule 2: Stability (total >= 10 per source)
- Rule 3 (bonus): Delta >= 0.05 noise gate
- Missing/incomplete sources fail
- Non-dict input safety
- Determinism
"""

from core.memory_stability_guard_layer import MemoryStabilityGuardLayer


def approx(a, b, eps=0.001):
    return abs(a - b) < eps


def run():
    guard = MemoryStabilityGuardLayer()
    passed = 0
    failed = 0

    def check(name, actual, expected):
        nonlocal passed, failed
        ok = actual == expected
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL {name}: expected {expected}, got {actual}")

    # Helper to build a valid performance state (all sources total >= 10)
    def stable_state(intent_correct=10, intent_total=10,
                     global_correct=10, global_total=10,
                     conflict_correct=10, conflict_total=10):
        return {
            "intent": {"correct": intent_correct, "total": intent_total},
            "global": {"correct": global_correct, "total": global_total},
            "conflict": {"correct": conflict_correct, "total": conflict_total},
        }

    # ── Test 1: All stable → allow_update = True ──────────────────────
    print("\n=== TEST 1: All Stable ===")
    result = guard.apply({
        "performance_state": stable_state(),
        "config": {},
    })
    check("all stable", result["allow_update"], True)

    # ── Test 2: Intent total < 5 → False ──────────────────────────────
    print("\n=== TEST 2: Intent total < 5 (Rule 1) ===")
    result = guard.apply({
        "performance_state": stable_state(intent_total=3),
        "config": {},
    })
    check("intent below min", result["allow_update"], False)

    # ── Test 3: Global total < 5 → False ──────────────────────────────
    print("\n=== TEST 3: Global total < 5 (Rule 1) ===")
    result = guard.apply({
        "performance_state": stable_state(global_total=4),
        "config": {},
    })
    check("global below min", result["allow_update"], False)

    # ── Test 4: Conflict total < 5 → False ────────────────────────────
    print("\n=== TEST 4: Conflict total < 5 (Rule 1) ===")
    result = guard.apply({
        "performance_state": stable_state(conflict_total=2),
        "config": {},
    })
    check("conflict below min", result["allow_update"], False)

    # ── Test 5: Intent total < 10 but >= 5 → False (Rule 2) ───────────
    print("\n=== TEST 5: Intent total 5–9 (Rule 2) ===")
    result = guard.apply({
        "performance_state": stable_state(intent_total=7),
        "config": {},
    })
    check("intent below stable", result["allow_update"], False)

    # ── Test 6: Global total < 10 but >= 5 → False (Rule 2) ───────────
    print("\n=== TEST 6: Global total 5–9 (Rule 2) ===")
    result = guard.apply({
        "performance_state": stable_state(global_total=8),
        "config": {},
    })
    check("global below stable", result["allow_update"], False)

    # ── Test 7: Conflict total < 10 but >= 5 → False (Rule 2) ─────────
    print("\n=== TEST 7: Conflict total 5–9 (Rule 2) ===")
    result = guard.apply({
        "performance_state": stable_state(conflict_total=6),
        "config": {},
    })
    check("conflict below stable", result["allow_update"], False)

    # ── Test 8: Missing source entry → False ──────────────────────────
    print("\n=== TEST 8: Missing Source Entry ===")
    result = guard.apply({
        "performance_state": {
            "intent": {"correct": 10, "total": 10},
            "global": {"correct": 10, "total": 10},
            # "conflict" is missing
        },
        "config": {},
    })
    check("missing source", result["allow_update"], False)

    # ── Test 9: Non-dict entry → False ────────────────────────────────
    print("\n=== TEST 9: Non-dict Entry ===")
    result = guard.apply({
        "performance_state": {
            "intent": "invalid",
            "global": {"correct": 10, "total": 10},
            "conflict": {"correct": 10, "total": 10},
        },
        "config": {},
    })
    check("non-dict entry", result["allow_update"], False)

    # ── Test 10: Non-dict input → False ───────────────────────────────
    print("\n=== TEST 10: Non-dict Input ===")
    result = guard.apply("invalid")
    check("non-dict input", result["allow_update"], False)

    # ── Test 11: Non-dict performance_state → False ───────────────────
    print("\n=== TEST 11: Non-dict Performance State ===")
    result = guard.apply({
        "performance_state": "invalid",
        "config": {},
    })
    check("non-dict state", result["allow_update"], False)

    # ── Test 12: Non-int total → False ────────────────────────────────
    print("\n=== TEST 12: Non-int Total ===")
    result = guard.apply({
        "performance_state": {
            "intent": {"correct": 10, "total": "10"},
            "global": {"correct": 10, "total": 10},
            "conflict": {"correct": 10, "total": 10},
        },
        "config": {},
    })
    check("non-int total", result["allow_update"], False)

    # ── Test 13: Noise gate — delta 0.04 < 0.05 → False ───────────────
    print("\n=== TEST 13: Noise Gate (delta too small) ===")
    # current: 10/10 = 1.0, previous: 0.96 → |1.0 - 0.96| = 0.04 < 0.05
    result = guard.apply({
        "performance_state": stable_state(intent_correct=10, intent_total=10),
        "config": {
            "previous_accuracy": {
                "intent": 0.96,
                "global": 0.5,
                "conflict": 0.5,
            }
        },
    })
    check("noise gate blocks", result["allow_update"], False)

    # ── Test 14: Noise gate — delta 0.05 >= 0.05 → passes ────────────
    print("\n=== TEST 14: Noise Gate Pass (delta >= 0.05) ===")
    # current: 10/10 = 1.0, previous: 0.95 → |1.0 - 0.95| = 0.05 >= 0.05
    result = guard.apply({
        "performance_state": stable_state(intent_correct=10, intent_total=10),
        "config": {
            "previous_accuracy": {
                "intent": 0.95,
                "global": 0.5,
                "conflict": 0.5,
            }
        },
    })
    check("noise gate passes at 0.05", result["allow_update"], True)

    # ── Test 15: Noise gate — intent passes, global fails → False ────
    print("\n=== TEST 15: Noise Gate — One Source Fails ===")
    # intent: |10/10 - 0.90| = 0.10 >= 0.05 → passes
    # global: |10/10 - 0.98| = 0.02 < 0.05  → fails
    result = guard.apply({
        "performance_state": stable_state(),
        "config": {
            "previous_accuracy": {
                "intent": 0.90,
                "global": 0.98,
                "conflict": 0.95,
            }
        },
    })
    check("global noise gate blocks", result["allow_update"], False)

    # ── Test 16: Noise gate skipped when no previous_accuracy ─────────
    print("\n=== TEST 16: No Previous Accuracy (noise gate skipped) ===")
    result = guard.apply({
        "performance_state": stable_state(),
        "config": {},
    })
    check("no prev_accuracy passes", result["allow_update"], True)

    # ── Test 17: Noise gate skipped when previous_accuracy is empty ───
    print("\n=== TEST 17: Empty Previous Accuracy ===")
    result = guard.apply({
        "performance_state": stable_state(),
        "config": {"previous_accuracy": {}},
    })
    check("empty prev_accuracy passes", result["allow_update"], True)

    # ── Test 18: Determinism ──────────────────────────────────────────
    print("\n=== TEST 18: Determinism ===")
    inp = {
        "performance_state": stable_state(),
        "config": {},
    }
    r1 = guard.apply(inp)
    r2 = guard.apply(inp)
    r3 = guard.apply(inp)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Test 19: Negative or zero total → False (Rule 1) ──────────────
    print("\n=== TEST 19: Zero Total ===")
    result = guard.apply({
        "performance_state": stable_state(intent_total=0),
        "config": {},
    })
    check("zero total", result["allow_update"], False)

    # ── Test 20: Non-dict config → treated as empty → noise gate skipped ─
    print("\n=== TEST 20: Non-dict Config ===")
    result = guard.apply({
        "performance_state": stable_state(),
        "config": "invalid",
    })
    check("non-dict config passes rules", result["allow_update"], True)

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
