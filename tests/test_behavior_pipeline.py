"""
Test script for BehaviorPipeline.

Validates:
- Full pipeline runs without errors
- Output format is correct {"behavior": ..., "decision_trace": ...}
- decision_trace contains all expected keys
- Determinism
- Edge cases (empty inputs, missing identity)
"""

from core.behavior_pipeline import BehaviorPipeline


def approx(a, b, eps=0.001):
    return abs(a - b) < eps


def run():
    pipeline = BehaviorPipeline()
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

    # ── Test 1: Basic run — strong intent ──────────────────────────
    print("\n=== TEST 1: Strong Intent ===")
    result = pipeline.run(
        intent="greeting",
        behavior={"tone": "neutral"},
        identity={
            "patterns": {
                "tone": {
                    "greeting": {
                        "casual": 6.0,
                        "formal": 2.0
                    }
                }
            },
            "global_patterns": {
                "tone": {
                    "technical": 3.0,
                    "casual": 2.0
                }
            }
        }
    )
    check("has behavior", "behavior" in result, True)
    check("has decision_trace", "decision_trace" in result, True)
    check("behavior tone", result["behavior"].get("tone"), "casual")
    trace = result["decision_trace"]
    check("trace intent", trace["intent"], "greeting")
    check("trace changed", trace["changed"], True)
    check("trace source", trace["source"], "intent")
    check("trace confidence > 0", trace["confidence"] > 0, True)
    check("trace has dimensions", "dimensions" in trace, True)
    check("trace dimensions has tone", "tone" in trace["dimensions"], True)
    check("trace dimensions has depth", "depth" in trace["dimensions"], True)
    check("trace dimensions has style", "style" in trace["dimensions"], True)
    check("tone source is intent", trace["dimensions"]["tone"]["source"], "intent")
    check("tone changed is True", trace["dimensions"]["tone"]["changed"], True)
    check("depth changed is False", trace["dimensions"]["depth"]["changed"], False)
    check("style changed is False", trace["dimensions"]["style"]["changed"], False)
    check("tone confidence > 0", trace["dimensions"]["tone"]["confidence"] > 0, True)
    check("has confidence_by_dimension", "confidence_by_dimension" in trace, True)
    check("cbd tone > 0", trace["confidence_by_dimension"]["tone"] > 0, True)
    check("cbd depth == 0", trace["confidence_by_dimension"]["depth"], 0.0)
    check("cbd style == 0", trace["confidence_by_dimension"]["style"], 0.0)

    # ── Test 2: Both medium — conflict layer may resolve ─────────

    print("\n=== TEST 2: Both Medium (conflict may resolve) ===")
    result = pipeline.run(
        intent="greeting",
        behavior={"tone": "neutral"},
        identity={
            "patterns": {
                "tone": {
                    "greeting": {
                        "casual": 3.0,
                        "formal": 2.8
                    }
                }
            },
            "global_patterns": {
                "tone": {
                    "technical": 3.2,
                    "casual": 3.0
                }
            }
        }
    )
    check("behavior exists", "tone" in result["behavior"], True)
    trace = result["decision_trace"]
    check("trace has intent", trace["intent"], "greeting")
    check("trace has confidence", isinstance(trace["confidence"], float), True)

    # ── Test 3: Strong global ─────────────────────────────────────
    print("\n=== TEST 3: Strong Global ===")
    result = pipeline.run(
        intent="greeting",
        behavior={"tone": "neutral"},
        identity={
            "patterns": {
                "tone": {
                    "greeting": {
                        "casual": 2.5,
                        "formal": 2.2
                    }
                }
            },
            "global_patterns": {
                "tone": {
                    "technical": 8.0,
                    "casual": 2.0
                }
            }
        }
    )
    check("global dominates", result["behavior"].get("tone"), "technical")
    trace = result["decision_trace"]
    check("trace source", trace["source"] in ("global", "conflict"), True)

    # ── Test 4: Empty behavior ────────────────────────────────────
    print("\n=== TEST 4: Empty Behavior ===")
    result = pipeline.run(
        intent="",
        behavior={},
        identity={},
    )
    check("empty behavior", result["behavior"], {})
    check("trace present", "decision_trace" in result, True)
    trace = result["decision_trace"]
    check("no change", trace["changed"], False)

    # ── Test 5: Determinism ───────────────────────────────────────
    print("\n=== TEST 5: Determinism ===")
    identity = {
        "patterns": {
            "tone": {
                "greeting": {"casual": 6.0, "formal": 2.0}
            }
        },
        "global_patterns": {
            "tone": {"technical": 3.0, "casual": 2.0}
        }
    }
    r1 = pipeline.run("greeting", {"tone": "neutral"}, identity)
    r2 = pipeline.run("greeting", {"tone": "neutral"}, identity)
    r3 = pipeline.run("greeting", {"tone": "neutral"}, identity)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Test 6: Non-dict identity ─────────────────────────────────
    print("\n=== TEST 6: Non-dict identity ===")
    result = pipeline.run("greeting", {"tone": "neutral"}, "invalid")
    check("behavior unchanged", result["behavior"], {"tone": "neutral"})
    check("trace present", "decision_trace" in result, True)

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
