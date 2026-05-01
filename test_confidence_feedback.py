"""
Test MemoryConfidenceFeedbackLayer with scaled confidence feedback.

Validates:
- Positive feedback increases weights correctly (intent, conflict, global)
- Negative feedback decreases weights correctly
- Scale: low confidence → smaller adjustment
- Scale: high confidence (>= 2.0) → full base adjustment
- Unchanged dimensions are skipped
- Missing values are not created
- Floor at 0 (no negative weights)
- Safety against missing/malformed inputs
- Determinism
"""

from core.memory_confidence_feedback_layer import MemoryConfidenceFeedbackLayer


def approx(a, b, eps=0.001):
    return abs(a - b) < eps


def _dim(source="none", changed=False, confidence=0.0):
    return {"source": source, "changed": changed, "confidence": confidence}


def run():
    layer = MemoryConfidenceFeedbackLayer()
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

    # ── Test 1: Positive feedback — intent (high confidence) ────────────
    print("\n=== TEST 1: Positive Feedback (intent, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none", changed=False),
                "style": _dim("none", changed=False),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("intent high conf +0.2", identity["patterns"]["tone"]["greeting"]["casual"], 6.2)
    check("formal unchanged", identity["patterns"]["tone"]["greeting"]["formal"], 2.0)

    # ── Test 2: Negative feedback — intent (high confidence) ────────────
    print("\n=== TEST 2: Negative Feedback (intent, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("intent high conf -0.2", identity["patterns"]["tone"]["greeting"]["casual"], 5.8)

    # ── Test 3: Positive feedback — conflict (high confidence) ──────────
    print("\n=== TEST 3: Positive Feedback (conflict, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("conflict", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("conflict high conf +0.15", identity["patterns"]["tone"]["greeting"]["casual"], 6.15)

    # ── Test 4: Negative feedback — conflict (high confidence) ──────────
    print("\n=== TEST 4: Negative Feedback (conflict, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("conflict", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("conflict high conf -0.15", identity["patterns"]["tone"]["greeting"]["casual"], 5.85)

    # ── Test 5: Positive feedback — global (high confidence) ────────────
    print("\n=== TEST 5: Positive Feedback (global, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "technical"},
            "dimensions": {
                "tone": _dim("global", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"technical": 6.0, "casual": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("global high conf +0.1", identity["patterns"]["tone"]["greeting"]["technical"], 6.1)

    # ── Test 6: Negative feedback — global (high confidence) ────────────
    print("\n=== TEST 6: Negative Feedback (global, confidence=2.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "technical"},
            "dimensions": {
                "tone": _dim("global", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"technical": 6.0, "casual": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("global high conf -0.1", identity["patterns"]["tone"]["greeting"]["technical"], 5.9)

    # ── Test 7: Low confidence → scaled adjustment ──────────────────────
    print("\n=== TEST 7: Low Confidence (scale=0.5) ===")
    # confidence=1.0 → scale = 1.0/2.0 = 0.5 → adjustment = 0.2 * 0.5 = 0.1
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=1.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("low conf positive", identity["patterns"]["tone"]["greeting"]["casual"], 6.1)

    # ── Test 8: Very low confidence → tiny adjustment ───────────────────
    print("\n=== TEST 8: Very Low Confidence (scale=0.25) ===")
    # confidence=0.5 → scale = 0.5/2.0 = 0.25 → adjustment = 0.2 * 0.25 = 0.05
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=0.5),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("very low conf positive", identity["patterns"]["tone"]["greeting"]["casual"], 6.05)

    # ── Test 9: Zero confidence → no adjustment ─────────────────────────
    print("\n=== TEST 9: Zero Confidence (no adjustment) ===")
    # confidence=0.0 → scale = 0.0 → adjustment = 0.0
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=0.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("zero conf no change", identity["patterns"]["tone"]["greeting"]["casual"], 6.0)

    # ── Test 10: High confidence negative → floor at 0 ──────────────────
    print("\n=== TEST 10: Floor at Zero (high confidence) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 0.1, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("floor at 0", identity["patterns"]["tone"]["greeting"]["casual"], 0.0)

    # ── Test 11: Unchanged dimensions are skipped ───────────────────────
    print("\n=== TEST 11: Skip Unchanged Dimension ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual", "depth": "deep"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("global", changed=False),  # changed=False → skip
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
                "depth": {
                    "greeting": {"deep": 5.0, "normal": 3.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("tone adjusted", identity["patterns"]["tone"]["greeting"]["casual"], 6.2)
    check("depth unchanged", identity["patterns"]["depth"]["greeting"]["deep"], 5.0)

    # ── Test 12: Do not create missing values ───────────────────────────
    print("\n=== TEST 12: Do Not Create Missing Values ===")
    identity_before = {
        "patterns": {
            "tone": {
                "greeting": {"formal": 2.0},  # "casual" does not exist
            },
        },
    }
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},  # not in patterns
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": identity_before,
    })
    identity = result["identity"]
    check("casual not created", "casual" in identity["patterns"]["tone"]["greeting"], False)
    check("formal unchanged", identity["patterns"]["tone"]["greeting"]["formal"], 2.0)

    # ── Test 13: Non-dict input ─────────────────────────────────────────
    print("\n=== TEST 13: Non-dict Input ===")
    result = layer.apply("invalid")
    check("empty identity", result["identity"], {})

    # ── Test 14: Missing identity ───────────────────────────────────────
    print("\n=== TEST 14: Missing Identity ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
    })
    check("empty identity when missing", result["identity"], {})

    # ── Test 15: Determinism ────────────────────────────────────────────
    print("\n=== TEST 15: Determinism ===")
    inp = {
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    }
    r1 = layer.apply(inp)
    r2 = layer.apply(inp)
    r3 = layer.apply(inp)
    check("determinism r1==r2", r1, r2)
    check("determinism r1==r3", r1, r3)

    # ── Test 16: Multiple dimensions changed ────────────────────────────
    print("\n=== TEST 16: Multiple Dimensions ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual", "style": "verbose"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("global", changed=True, confidence=2.0),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
                "style": {
                    "greeting": {"verbose": 4.0, "concise": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("multi tone +0.2", identity["patterns"]["tone"]["greeting"]["casual"], 6.2)
    check("multi style +0.1", identity["patterns"]["style"]["greeting"]["verbose"], 4.1)

    # ── Test 17: Non-bool feedback defaults to False ────────────────────
    print("\n=== TEST 17: Non-bool Feedback ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": "not_a_bool",
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("non-bool defaults to False", identity["patterns"]["tone"]["greeting"]["casual"], 5.8)

    # ── Test 18: Negative low confidence ────────────────────────────────
    print("\n=== TEST 18: Negative Low Confidence (scale=0.5) ===")
    # confidence=1.0 → scale=0.5 → adjustment = 0.2*0.5 = 0.1
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=1.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("low conf negative", identity["patterns"]["tone"]["greeting"]["casual"], 5.9)

    # ── Test 19: Confidence above 2.0 still caps at 1.0 scale ───────────
    print("\n=== TEST 19: Very High Confidence (caps at 1.0) ===")
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=10.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 6.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("very high conf caps at +0.2", identity["patterns"]["tone"]["greeting"]["casual"], 6.2)

    # ── Test 20: MAX_WEIGHT soft cap (no runaway) ─────────────────────
    print("\n=== TEST 20: MAX_WEIGHT Soft Cap ===")
    # Start at 9.9 + 0.2 = 10.1 → should cap at 10.0
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 9.9, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("soft cap at 10.0", identity["patterns"]["tone"]["greeting"]["casual"], 10.0)

    # Already at 10.0 + 0.2 = 10.2 → should stay at 10.0
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 10.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("already at max stays capped", identity["patterns"]["tone"]["greeting"]["casual"], 10.0)

    # Well above 10.0 (e.g. 15.0 with negative feedback = 14.8) → should cap at 10.0
    # Actually negative: 15.0 - 0.2 = 14.8 → min(10.0, 14.8) = 10.0
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": False,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 15.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("far above max capped at 10.0", identity["patterns"]["tone"]["greeting"]["casual"], 10.0)

    # Normal weight below 10.0 shouldn't be affected by cap
    result = layer.apply({
        "decision_trace": {
            "intent": "greeting",
            "after": {"tone": "casual"},
            "dimensions": {
                "tone": _dim("intent", changed=True, confidence=2.0),
                "depth": _dim("none"),
                "style": _dim("none"),
            },
        },
        "feedback": True,
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {"casual": 5.0, "formal": 2.0},
                },
            },
        },
    })
    identity = result["identity"]
    check("below cap unaffected", identity["patterns"]["tone"]["greeting"]["casual"], 5.2)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*40}")
    print(f"  PASSED: {passed}  FAILED: {failed}  TOTAL: {passed + failed}")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run()
