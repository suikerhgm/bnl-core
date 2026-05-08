"""
Test MemoryPerformanceTracker.

Validates:
- Intent source tracking (correct/total increments)
- Global source tracking
- Conflict source tracking
- Unknown sources are ignored
- Non-bool feedback defaults to False
- Missing state initializes correctly
- Non-dict input safety
- Determinism
"""

from core.memory_performance_tracker import MemoryPerformanceTracker


def run():
    tracker = MemoryPerformanceTracker()
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

    # ── Test 1: Intent positive feedback ──────────────────────────────
    print("\n=== TEST 1: Intent Positive Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": True,
        "state": {},
    })
    s = result["state"]
    check("intent total", s["intent"]["total"], 1)
    check("intent correct", s["intent"]["correct"], 1)

    # ── Test 2: Intent negative feedback ──────────────────────────────
    print("\n=== TEST 2: Intent Negative Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": False,
        "state": {"intent": {"correct": 1, "total": 1}},
    })
    s = result["state"]
    check("intent total+1", s["intent"]["total"], 2)
    check("intent correct unchanged", s["intent"]["correct"], 1)

    # ── Test 3: Global positive feedback ──────────────────────────────
    print("\n=== TEST 3: Global Positive Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "global"},
        "feedback": True,
        "state": {},
    })
    s = result["state"]
    check("global total", s["global"]["total"], 1)
    check("global correct", s["global"]["correct"], 1)

    # ── Test 4: Global negative feedback ──────────────────────────────
    print("\n=== TEST 4: Global Negative Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "global"},
        "feedback": False,
        "state": {"global": {"correct": 2, "total": 3}},
    })
    s = result["state"]
    check("global total+1", s["global"]["total"], 4)
    check("global correct unchanged", s["global"]["correct"], 2)

    # ── Test 5: Conflict positive feedback ────────────────────────────
    print("\n=== TEST 5: Conflict Positive Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "conflict"},
        "feedback": True,
        "state": {},
    })
    s = result["state"]
    check("conflict total", s["conflict"]["total"], 1)
    check("conflict correct", s["conflict"]["correct"], 1)

    # ── Test 6: Conflict negative feedback ────────────────────────────
    print("\n=== TEST 6: Conflict Negative Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "conflict"},
        "feedback": False,
        "state": {"conflict": {"correct": 5, "total": 10}},
    })
    s = result["state"]
    check("conflict total+1", s["conflict"]["total"], 11)
    check("conflict correct unchanged", s["conflict"]["correct"], 5)

    # ── Test 7: Unknown source ignored ────────────────────────────────
    print("\n=== TEST 7: Unknown Source Ignored ===")
    state_in = {"intent": {"correct": 1, "total": 1}}
    result = tracker.apply({
        "decision_trace": {"source": "unknown"},
        "feedback": True,
        "state": state_in,
    })
    s = result["state"]
    check("unknown source unchanged", s["intent"]["correct"], 1)
    check("unknown source total same", s["intent"]["total"], 1)
    check("unknown not created", "unknown" in s, False)

    # ── Test 8: Non-bool feedback defaults to False ───────────────────
    print("\n=== TEST 8: Non-bool Feedback ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": "not_a_bool",
        "state": {"intent": {"correct": 0, "total": 0}},
    })
    s = result["state"]
    check("non-bool total+1", s["intent"]["total"], 1)
    check("non-bool correct unchanged", s["intent"]["correct"], 0)

    # ── Test 9: Missing state initializes correctly ───────────────────
    print("\n=== TEST 9: Missing State ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": True,
    })
    s = result["state"]
    check("missing state total", s["intent"]["total"], 1)
    check("missing state correct", s["intent"]["correct"], 1)

    # ── Test 10: Non-dict input ───────────────────────────────────────
    print("\n=== TEST 10: Non-dict Input ===")
    result = tracker.apply("invalid")
    check("non-dict state", result["state"], {})

    # ── Test 11: Non-dict decision_trace ──────────────────────────────
    print("\n=== TEST 11: Non-dict Decision Trace ===")
    result = tracker.apply({
        "decision_trace": "invalid",
        "feedback": True,
        "state": {"intent": {"correct": 0, "total": 0}},
    })
    s = result["state"]
    check("non-dict trace state returned", s["intent"]["correct"], 0)

    # ── Test 12: Non-dict state ───────────────────────────────────────
    print("\n=== TEST 12: Non-dict State ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": True,
        "state": "invalid",
    })
    s = result["state"]
    check("non-dict state init total", s["intent"]["total"], 1)
    check("non-dict state init correct", s["intent"]["correct"], 1)

    # ── Test 13: Malformed entry (not a dict) ─────────────────────────
    print("\n=== TEST 13: Malformed Entry ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": True,
        "state": {"intent": "not_a_dict"},
    })
    s = result["state"]
    check("malformed entry reset total", s["intent"]["total"], 1)
    check("malformed entry reset correct", s["intent"]["correct"], 1)

    # ── Test 14: Missing keys in entry ────────────────────────────────
    print("\n=== TEST 14: Missing Keys in Entry ===")
    result = tracker.apply({
        "decision_trace": {"source": "intent"},
        "feedback": True,
        "state": {"intent": {}},
    })
    s = result["state"]
    check("missing keys total", s["intent"]["total"], 1)
    check("missing keys correct", s["intent"]["correct"], 1)

    # ── Test 15: Mixed sources tracked independently ──────────────────
    print("\n=== TEST 15: Mixed Sources ===")
    state_mixed = {}
    for src in ["intent", "global", "conflict"]:
        for _ in range(3):
            state_mixed = tracker.apply({
                "decision_trace": {"source": src},
                "feedback": True,
                "state": state_mixed,
            })["state"]
    for src in ["intent", "global", "conflict"]:
        check(f"{src} total 3", state_mixed[src]["total"], 3)
        check(f"{src} correct 3", state_mixed[src]["correct"], 3)

    # ── Test 16: Determinism ──────────────────────────────────────────
    print("\n=== TEST 16: Determinism ===")
    inp = {
        "decision_trace": {"source": "intent"},
        "feedback": True,
        "state": {"intent": {"correct": 5, "total": 5}},
    }
    r1 = tracker.apply(inp)
    r2 = tracker.apply(inp)
    r3 = tracker.apply(inp)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Test 17: Feedback=True multiple times accumulates ─────────────
    print("\n=== TEST 17: Accumulation ===")
    state_acc = {}
    for _ in range(10):
        state_acc = tracker.apply({
            "decision_trace": {"source": "intent"},
            "feedback": True,
            "state": state_acc,
        })["state"]
    check("accumulate total 10", state_acc["intent"]["total"], 10)
    check("accumulate correct 10", state_acc["intent"]["correct"], 10)

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
