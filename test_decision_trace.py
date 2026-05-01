"""
Test MemoryDecisionTraceLayer with per-dimension decision scenarios.

Validates:
- per-dimension source detection (intent, global, conflict, none)
- overall source detection (same for all, mixed, none)
- per-dimension confidence computation
- signal strength extraction
- safety against missing/metadata edge cases
- determinism
"""

from core.memory_decision_trace_layer import MemoryDecisionTraceLayer


def approx(a, b, eps=0.001):
    """Compare floats with tolerance."""
    return abs(a - b) < eps


def _dim(source, intent_strength=0.0, global_strength=0.0, top_score=0.0, second_score=0.0):
    """Helper to build a per-dimension metadata entry."""
    return {
        "source": source,
        "intent_strength": intent_strength,
        "global_strength": global_strength,
        "top_score": top_score,
        "second_score": second_score,
    }


def run():
    layer = MemoryDecisionTraceLayer()
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

    # ── Test 1: Intent source (tone only changed) ───────────────────────
    print("\n=== TEST 1: Intent Source (single dimension) ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "casual"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("intent", intent_strength=8.0, global_strength=3.5, top_score=6.0, second_score=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("intent", trace["intent"], "greeting")
    check("changed", trace["changed"], True)
    check("source", trace["source"], "intent")
    check("confidence", trace["confidence"], 6.0 / 2.000001)
    check("intent_strength", trace["signals"]["intent_strength"], 8.0)
    check("combined_used", trace["signals"]["combined_used"], False)
    check("has dimensions key", "dimensions" in trace, True)
    check("tone source in dimensions", trace["dimensions"]["tone"]["source"], "intent")
    check("depth source in dimensions", trace["dimensions"]["depth"]["source"], "none")
    check("style source in dimensions", trace["dimensions"]["style"]["source"], "none")
    check("tone changed in dimensions", trace["dimensions"]["tone"]["changed"], True)
    check("depth changed in dimensions", trace["dimensions"]["depth"]["changed"], False)
    check("has confidence_by_dimension", "confidence_by_dimension" in trace, True)
    check("cbd tone", trace["confidence_by_dimension"]["tone"], 6.0 / 2.000001)
    check("cbd depth", trace["confidence_by_dimension"]["depth"], 0.0)
    check("cbd style", trace["confidence_by_dimension"]["style"], 0.0)

    # ── Test 2: Global source ───────────────────────────────────────────

    print("\n=== TEST 2: Global Source ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "technical"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("global", intent_strength=2.0, global_strength=8.0, top_score=8.0, second_score=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("source", trace["source"], "global")
    check("confidence", trace["confidence"], 8.0 / 2.000001)
    check("intent_strength", trace["signals"]["intent_strength"], 2.0)
    check("global_strength", trace["signals"]["global_strength"], 8.0)

    # ── Test 3: Conflict source ─────────────────────────────────────────
    print("\n=== TEST 3: Conflict Source ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "casual"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("conflict", intent_strength=4.0, global_strength=4.0, top_score=5.0, second_score=1.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("source", trace["source"], "conflict")
    check("confidence", trace["confidence"], 5.0 / 1.000001)
    check("combined_used", trace["signals"]["combined_used"], True)

    # ── Test 4: Mixed source (tone intent, depth global) ────────────────
    print("\n=== TEST 4: Mixed Sources ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral", "depth": "normal"},
        "behavior_after": {"tone": "casual", "depth": "deep"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("intent", intent_strength=8.0, top_score=6.0, second_score=2.0),
                "depth": _dim("global", global_strength=7.0, top_score=7.0, second_score=1.0),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("source mixed", trace["source"], "mixed")
    check("confidence mixed", trace["confidence"], 7.0 / 1.000001)  # max of changed dims
    check("tone source", trace["dimensions"]["tone"]["source"], "intent")
    check("depth source", trace["dimensions"]["depth"]["source"], "global")

    # ── Test 5: None / no change ────────────────────────────────────────
    print("\n=== TEST 5: No Change ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "neutral"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("none"),
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("changed", trace["changed"], False)
    check("source", trace["source"], "none")
    check("confidence", trace["confidence"], 0.0)
    check("intent_strength", trace["signals"]["intent_strength"], 0.0)

    # ── Test 6: Missing metadata ────────────────────────────────────────
    print("\n=== TEST 6: Missing Metadata ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "casual"},
        "identity": {},
    })
    trace = result["decision_trace"]
    check("source (missing)", trace["source"], "none")
    check("confidence (missing)", trace["confidence"], 0.0)
    check("intent_strength (missing)", trace["signals"]["intent_strength"], 0.0)
    check("global_strength (missing)", trace["signals"]["global_strength"], 0.0)
    check("combined_used (missing)", trace["signals"]["combined_used"], False)

    # ── Test 7: Malformed metadata values ───────────────────────────────
    print("\n=== TEST 7: Malformed Metadata ===")
    result = layer.apply({
        "intent": "greeting",
        "behavior_before": {},
        "behavior_after": {},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": {
                    "source": "intent",
                    "intent_strength": "not_a_number",
                    "global_strength": None,
                    "top_score": -5.0,
                    "second_score": 0.0,
                },
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    })
    trace = result["decision_trace"]
    check("intent_strength bad", trace["signals"]["intent_strength"], 0.0)
    check("global_strength none", trace["signals"]["global_strength"], 0.0)
    check("confidence bad data", trace["confidence"], 0.0)

    # ── Test 8: Non-dict input ──────────────────────────────────────────
    print("\n=== TEST 8: Non-dict Input ===")
    result = layer.apply("invalid")
    trace = result["decision_trace"]
    check("intent empty", trace["intent"], "")
    check("changed false", trace["changed"], False)
    check("source none", trace["source"], "none")
    check("confidence zero", trace["confidence"], 0.0)

    # ── Test 9: Determinism ─────────────────────────────────────────────
    print("\n=== TEST 9: Determinism ===")
    inp = {
        "intent": "greeting",
        "behavior_before": {"tone": "neutral"},
        "behavior_after": {"tone": "technical"},
        "identity": {},
        "metadata": {
            "dimensions": {
                "tone": _dim("global", intent_strength=3.0, global_strength=7.5, top_score=8.0, second_score=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            }
        }
    }
    r1 = layer.apply(inp)
    r2 = layer.apply(inp)
    r3 = layer.apply(inp)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
