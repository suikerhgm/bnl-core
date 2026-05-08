"""
Test MemoryAdaptiveStrategyLayer.

Validates:
- Intent accuracy > 0.7 → intent_weight_factor += 0.1
- Global accuracy < 0.5 → global_weight_factor -= 0.1
- Conflict accuracy > 0.8 → dominance_threshold -= 0.1
- Multiple rules apply simultaneously
- Clamping: dominance_threshold (1.1–2.0), weights (0.1–1.0)
- Missing/incomplete sources are handled
- Default config when no config provided
- Non-dict input safety
- Determinism
"""

from core.memory_adaptive_strategy_layer import MemoryAdaptiveStrategyLayer


def approx(a, b, eps=0.001):
    return abs(a - b) < eps


def run():
    layer = MemoryAdaptiveStrategyLayer()
    passed = 0
    failed = 0

    def check(name, actual, expected):
        nonlocal passed, failed
        if isinstance(expected, float):
            ok = approx(actual, expected)
        else:
            ok = actual == expected
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL {name}: expected {expected}, got {actual}")

    # ── Test 1: Intent accuracy > 0.7 boosts intent_weight_factor ─────
    print("\n=== TEST 1: Intent High Accuracy ===")
    result = layer.apply({
        "performance_state": {
            "intent": {"correct": 8, "total": 10},   # 0.8 > 0.7
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("intent_weight_factor boosted", c["intent_weight_factor"], 0.6)
    check("dominance_threshold unchanged", c["dominance_threshold"], 1.5)
    check("global_weight_factor unchanged", c["global_weight_factor"], 0.5)

    # ── Test 2: Intent accuracy at boundary (0.7) does NOT trigger ────
    print("\n=== TEST 2: Intent Accuracy at 0.7 (no trigger) ===")
    result = layer.apply({
        "performance_state": {
            "intent": {"correct": 7, "total": 10},   # 0.7, not > 0.7
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("intent not boosted at boundary", c["intent_weight_factor"], 0.5)

    # ── Test 3: Global accuracy < 0.5 penalizes global_weight_factor ──
    print("\n=== TEST 3: Global Low Accuracy ===")
    result = layer.apply({
        "performance_state": {
            "global": {"correct": 2, "total": 10},   # 0.2 < 0.5
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("global_weight_factor penalized", c["global_weight_factor"], 0.4)

    # ── Test 4: Global accuracy at boundary (0.5) does NOT trigger ────
    print("\n=== TEST 4: Global Accuracy at 0.5 (no trigger) ===")
    result = layer.apply({
        "performance_state": {
            "global": {"correct": 5, "total": 10},   # 0.5, not < 0.5
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("global not penalized at boundary", c["global_weight_factor"], 0.5)

    # ── Test 5: Conflict accuracy > 0.8 lowers dominance_threshold ────
    print("\n=== TEST 5: Conflict High Accuracy ===")
    result = layer.apply({
        "performance_state": {
            "conflict": {"correct": 9, "total": 10},  # 0.9 > 0.8
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("dominance_threshold lowered", c["dominance_threshold"], 1.4)

    # ── Test 6: Conflict accuracy at boundary (0.8) does NOT trigger ──
    print("\n=== TEST 6: Conflict Accuracy at 0.8 (no trigger) ===")
    result = layer.apply({
        "performance_state": {
            "conflict": {"correct": 8, "total": 10},  # 0.8, not > 0.8
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("dominance not lowered at boundary", c["dominance_threshold"], 1.5)

    # ── Test 7: All rules trigger simultaneously ───────────────────────
    print("\n=== TEST 7: All Rules Trigger ===")
    result = layer.apply({
        "performance_state": {
            "intent": {"correct": 8, "total": 10},     # 0.8 > 0.7  → +0.1
            "global": {"correct": 2, "total": 10},     # 0.2 < 0.5  → -0.1
            "conflict": {"correct": 9, "total": 10},   # 0.9 > 0.8  → -0.1
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("all intent boosted", c["intent_weight_factor"], 0.6)
    check("all global penalized", c["global_weight_factor"], 0.4)
    check("all dominance lowered", c["dominance_threshold"], 1.4)

    # ── Test 8: Missing source → no change ────────────────────────────
    print("\n=== TEST 8: Missing Source ===")
    result = layer.apply({
        "performance_state": {},
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("missing source all default", c["intent_weight_factor"], 0.5)
    check("missing source dominance", c["dominance_threshold"], 1.5)
    check("missing source global", c["global_weight_factor"], 0.5)

    # ── Test 9: Source with total=0 → no change ───────────────────────
    print("\n=== TEST 9: Zero Total Source ===")
    result = layer.apply({
        "performance_state": {
            "intent": {"correct": 0, "total": 0},
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("zero total unchanged", c["intent_weight_factor"], 0.5)

    # ── Test 10: Clamp dominance_threshold min (1.1) ──────────────────
    print("\n=== TEST 10: Clamp Dominance Min ===")
    result = layer.apply({
        "performance_state": {
            "conflict": {"correct": 10, "total": 10},  # 1.0 > 0.8 → -0.1
        },
        "config": {"dominance_threshold": 1.1, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("dominance clamped at min", c["dominance_threshold"], 1.1)

    # ── Test 11: Clamp dominance_threshold max (2.0) ──────────────────
    print("\n=== TEST 11: Clamp Dominance Max ===")
    # conflict low accuracy → no reduction, but starting value is fine
    # We just verify high initial values are capped: start above max to test
    # Actually no rule increases dominance, so we test that it doesn't go above 2.0
    # Start at 2.5, ensure clamped to 2.0
    result = layer.apply({
        "performance_state": {},
        "config": {"dominance_threshold": 2.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("dominance clamped at max", c["dominance_threshold"], 2.0)

    # ── Test 12: Clamp weight factor min (0.1) ────────────────────────
    print("\n=== TEST 12: Clamp Weight Min ===")
    result = layer.apply({
        "performance_state": {
            "global": {"correct": 0, "total": 10},  # 0.0 < 0.5 → -0.1
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.1, "global_weight_factor": 0.1},
    })
    c = result["config"]
    check("global weight clamped at min", c["global_weight_factor"], 0.1)

    # ── Test 13: Clamp weight factor max (1.0) ────────────────────────
    print("\n=== TEST 13: Clamp Weight Max ===")
    result = layer.apply({
        "performance_state": {
            "intent": {"correct": 10, "total": 10},  # 1.0 > 0.7 → +0.1
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 1.0, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("intent weight clamped at max", c["intent_weight_factor"], 1.0)

    # ── Test 14: Non-dict input ───────────────────────────────────────
    print("\n=== TEST 14: Non-dict Input ===")
    result = layer.apply("invalid")
    c = result["config"]
    check("non-dict uses defaults", c["dominance_threshold"], 1.5)
    check("non-dict default intent", c["intent_weight_factor"], 0.5)
    check("non-dict default global", c["global_weight_factor"], 0.5)

    # ── Test 15: Non-dict performance_state ───────────────────────────
    print("\n=== TEST 15: Non-dict Performance State ===")
    result = layer.apply({
        "performance_state": "invalid",
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("non-dict perf state unchanged", c["intent_weight_factor"], 0.5)

    # ── Test 16: Missing config uses defaults ─────────────────────────
    print("\n=== TEST 16: Missing Config ===")
    result = layer.apply({
        "performance_state": {},
    })
    c = result["config"]
    check("missing config default threshold", c["dominance_threshold"], 1.5)
    check("missing config default intent", c["intent_weight_factor"], 0.5)
    check("missing config default global", c["global_weight_factor"], 0.5)

    # ── Test 17: Partial config fills missing keys ────────────────────
    print("\n=== TEST 17: Partial Config ===")
    result = layer.apply({
        "performance_state": {},
        "config": {"dominance_threshold": 1.7},
    })
    c = result["config"]
    check("partial config threshold kept", c["dominance_threshold"], 1.7)
    check("partial config default intent", c["intent_weight_factor"], 0.5)
    check("partial config default global", c["global_weight_factor"], 0.5)

    # ── Test 18: Determinism ──────────────────────────────────────────
    print("\n=== TEST 18: Determinism ===")
    inp = {
        "performance_state": {
            "intent": {"correct": 8, "total": 10},
            "conflict": {"correct": 9, "total": 10},
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    }
    r1 = layer.apply(inp)
    r2 = layer.apply(inp)
    r3 = layer.apply(inp)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Test 19: Repeated applications compound ───────────────────────
    print("\n=== TEST 19: Repeated Application ===")
    state = {"correct": 9, "total": 10}  # 0.9 (>0.7)
    config = {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5}
    for i in range(4):
        result = layer.apply({
            "performance_state": {"intent": state},
            "config": config,
        })
        config = result["config"]
    check("repeated intent boost x4", config["intent_weight_factor"], 0.9)

    # ── Test 20: Non-dict entry in performance_state ──────────────────
    print("\n=== TEST 20: Non-dict Entry ===")
    result = layer.apply({
        "performance_state": {
            "intent": "invalid",
        },
        "config": {"dominance_threshold": 1.5, "intent_weight_factor": 0.5, "global_weight_factor": 0.5},
    })
    c = result["config"]
    check("non-dict entry unchanged", c["intent_weight_factor"], 0.5)

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
