"""
Tests for MemoryPatternDecayLayer.

Verifies:
  - Determinism
  - Core decay logic
  - Pruning behavior
  - Safety against malformed data
  - No mutation of original input
"""

import copy
from core.memory_pattern_decay_layer import MemoryPatternDecayLayer, DECAY_FACTOR, PRUNE_THRESHOLD

layer = MemoryPatternDecayLayer()


def assert_eq(a, b, msg=""):
    assert a == b, f"{msg}: expected {b}, got {a}"


def test_empty_input():
    """Empty input returns safe structure."""
    r = layer.apply({})
    assert_eq(r, {"identity": {}})


def test_no_identity():
    """Missing identity returns safe structure."""
    r = layer.apply({"foo": "bar"})
    assert_eq(r, {"identity": {}})


def test_identity_not_dict():
    """Non-dict identity returns safe structure."""
    r = layer.apply({"identity": "string"})
    assert_eq(r, {"identity": {}})


def test_no_patterns():
    """Missing patterns returns identity unchanged."""
    r = layer.apply({"identity": {"name": "test"}})
    assert_eq(r, {"identity": {"name": "test", "patterns": {}}})


def test_patterns_not_dict():
    """Non-dict patterns returns identity unchanged (no patterns key added)."""
    r = layer.apply({"identity": {"patterns": "invalid"}})
    assert_eq(r, {"identity": {"patterns": "invalid"}})


def test_simple_decay():
    """A single weight decays by DECAY_FACTOR."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim1": {
                    "intent1": {
                        "value_a": 1.0
                    }
                }
            }
        }
    })
    expected = 1.0 * DECAY_FACTOR
    got = r["identity"]["patterns"]["dim1"]["intent1"]["value_a"]
    assert_eq(got, expected, f"Expected {expected}, got {got}")


def test_multiple_values():
    """Multiple values in same intent all decay correctly."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {
                        "a": 0.5,
                        "b": 1.0,
                        "c": 0.75
                    }
                }
            }
        }
    })
    vals = r["identity"]["patterns"]["dim"]["int"]
    assert_eq(vals["a"], 0.5 * DECAY_FACTOR)
    assert_eq(vals["b"], 1.0 * DECAY_FACTOR)
    assert_eq(vals["c"], 0.75 * DECAY_FACTOR)


def test_multiple_intents():
    """Multiple intents all decay correctly."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int_a": {"v1": 0.8},
                    "int_b": {"v2": 0.3}
                }
            }
        }
    })
    assert_eq(r["identity"]["patterns"]["dim"]["int_a"]["v1"], 0.8 * DECAY_FACTOR)
    assert_eq(r["identity"]["patterns"]["dim"]["int_b"]["v2"], 0.3 * DECAY_FACTOR)


def test_multiple_dimensions():
    """Multiple dimensions all decay correctly."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim_a": {
                    "int": {"v": 0.9}
                },
                "dim_b": {
                    "int": {"v": 0.4}
                }
            }
        }
    })
    assert_eq(r["identity"]["patterns"]["dim_a"]["int"]["v"], 0.9 * DECAY_FACTOR)
    assert_eq(r["identity"]["patterns"]["dim_b"]["int"]["v"], 0.4 * DECAY_FACTOR)


def test_prune_below_threshold():
    """Values below PRUNE_THRESHOLD after decay are removed."""
    # 0.04 * 0.995 = 0.0398 < 0.05 → pruned
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {
                        "low": 0.04,
                        "high": 1.0
                    }
                }
            }
        }
    })
    vals = r["identity"]["patterns"]["dim"]["int"]
    assert "low" not in vals, "low value should have been pruned"
    assert_eq(vals["high"], 1.0 * DECAY_FACTOR)


def test_prune_edge_threshold():
    """Values exactly at threshold edge behave correctly."""
    # At threshold: 0.05 * 0.995 = 0.04975 < 0.05 → pruned
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {
                        "edge": 0.05
                    }
                }
            }
        }
    })
    # After pruning, "int" is empty and gets removed; "dim" stays as empty dict
    assert_eq(r["identity"]["patterns"]["dim"], {}, "dim should exist but be empty")

    # Just above: 0.051 * 0.995 = 0.050745 >= 0.05 → kept
    r2 = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {
                        "above": 0.051
                    }
                }
            }
        }
    })
    assert_eq(r2["identity"]["patterns"]["dim"]["int"]["above"], 0.051 * DECAY_FACTOR)


def test_remove_empty_intent():
    """If all values in an intent are pruned, the intent is removed."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int_a": {"v1": 0.04},
                    "int_b": {"v2": 1.0}
                }
            }
        }
    })
    patterns = r["identity"]["patterns"]["dim"]
    assert "int_a" not in patterns, "empty intent should be removed"
    assert "int_b" in patterns, "non-empty intent should remain"


def test_do_not_remove_top_level_dimension():
    """Even if all intents in a dimension are pruned, the dimension key remains."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim_empty": {
                    "int": {"v": 0.04}
                },
                "dim_full": {
                    "int": {"v": 1.0}
                }
            }
        }
    })
    patterns = r["identity"]["patterns"]
    assert "dim_empty" in patterns, "top-level dimension must NOT be removed"
    assert "dim_full" in patterns, "non-empty dimension must remain"
    # The empty dimension should have an empty dict
    assert_eq(patterns["dim_empty"], {}, "empty dimension should be empty dict")


def test_invalid_weight_types():
    """Non-numeric weights are silently ignored."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {
                        "good": 0.5,
                        "bad_str": "hello",
                        "bad_list": [1, 2, 3],
                        "bad_none": None,
                        "bad_bool": True
                    }
                }
            }
        }
    })
    vals = r["identity"]["patterns"]["dim"]["int"]
    assert_eq(vals["good"], 0.5 * DECAY_FACTOR)
    assert "bad_str" not in vals
    assert "bad_list" not in vals
    assert "bad_none" not in vals
    assert "bad_bool" not in vals


def test_malformed_intents():
    """Non-dict intents are silently skipped."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "good_intent": {"v": 0.5},
                    "bad_intent": "string",
                    "also_bad": 42
                }
            }
        }
    })
    assert "good_intent" in r["identity"]["patterns"]["dim"]
    assert "bad_intent" not in r["identity"]["patterns"]["dim"]
    assert "also_bad" not in r["identity"]["patterns"]["dim"]


def test_no_new_keys():
    """The layer does NOT create any keys that weren't in the input."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {"v": 0.5}
                }
            }
        }
    })
    # Only the expected keys
    assert set(r.keys()) == {"identity"}
    assert set(r["identity"].keys()) == {"patterns"}


def test_no_normalization():
    """Values should NOT be normalized or altered other than decay."""
    original = 2.0
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {"v": original}
                }
            }
        }
    })
    got = r["identity"]["patterns"]["dim"]["int"]["v"]
    expected = original * DECAY_FACTOR
    assert_eq(got, expected, "values should only be multiplied by decay_factor")


def test_int_weight():
    """Integer weights are handled correctly."""
    r = layer.apply({
        "identity": {
            "patterns": {
                "dim": {
                    "int": {"v": 2}
                }
            }
        }
    })
    got = r["identity"]["patterns"]["dim"]["int"]["v"]
    expected = 2 * DECAY_FACTOR
    assert_eq(got, expected, f"int decay failed: {got} != {expected}")


def test_determinism():
    """Multiple calls with same input produce identical output."""
    inp = {
        "identity": {
            "patterns": {
                "dim": {
                    "int": {"v": 0.5}
                }
            }
        }
    }
    r1 = layer.apply(inp)
    r2 = layer.apply(inp)
    assert r1 == r2, "determinism violated"


def test_does_not_mutate_original():
    """The original input dict must not be mutated."""
    original = {
        "identity": {
            "patterns": {
                "dim": {
                    "int": {"v": 0.5}
                }
            }
        }
    }
    frozen = copy.deepcopy(original)
    layer.apply(original)
    assert_eq(original, frozen, "original input was mutated")


def test_deeply_nested_nontrivial():
    """Complex nested structure with mixed valid/invalid data."""
    inp = {
        "identity": {
            "patterns": {
                "behavior": {
                    "social": {
                        "friendly": 0.8,
                        "reserved": 0.06,
                        "aggressive": 0.02
                    },
                    "work": {
                        "focused": 1.2,
                        "lazy": "yes",
                        "distracted": None
                    }
                },
                "preferences": {
                    "food": {
                        "spicy": 0.3,
                        "sweet": 0.7
                    }
                },
                "empty_dim": {
                    "empty_intent": {
                        "tiny": 0.01
                    }
                }
            },
            "other_data": {
                "should": "remain untouched"
            }
        }
    }
    r = layer.apply(inp)
    p = r["identity"]["patterns"]

    # behavior → social
    social = p["behavior"]["social"]
    assert_eq(social["friendly"], 0.8 * DECAY_FACTOR)
    assert "reserved" in social  # 0.06 * 0.995 = 0.0597 >= 0.05
    assert_eq(social["reserved"], 0.06 * DECAY_FACTOR)
    assert "aggressive" not in social  # 0.02 * 0.995 = 0.0199 < 0.05

    # behavior → work
    work = p["behavior"]["work"]
    assert_eq(work["focused"], 1.2 * DECAY_FACTOR)
    assert "lazy" not in work
    assert "distracted" not in work

    # preferences → food
    food = p["preferences"]["food"]
    assert_eq(food["spicy"], 0.3 * DECAY_FACTOR)
    assert_eq(food["sweet"], 0.7 * DECAY_FACTOR)

    # empty_dim should still exist but be empty
    assert_eq(p["empty_dim"], {})

    # other_data untouched
    assert_eq(r["identity"]["other_data"], {"should": "remain untouched"})


# ── Run all ──

def run_all():
    tests = [
        test_empty_input,
        test_no_identity,
        test_identity_not_dict,
        test_no_patterns,
        test_patterns_not_dict,
        test_simple_decay,
        test_multiple_values,
        test_multiple_intents,
        test_multiple_dimensions,
        test_prune_below_threshold,
        test_prune_edge_threshold,
        test_remove_empty_intent,
        test_do_not_remove_top_level_dimension,
        test_invalid_weight_types,
        test_malformed_intents,
        test_no_new_keys,
        test_no_normalization,
        test_int_weight,
        test_determinism,
        test_does_not_mutate_original,
        test_deeply_nested_nontrivial,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*40}")
    print(f"  {passed}/{total} tests passed")
    if failed:
        print(f"  {failed} FAILED")
    else:
        print(f"  All tests passed!")
    print(f"{'='*40}")

    return failed == 0


if __name__ == "__main__":
    run_all()
