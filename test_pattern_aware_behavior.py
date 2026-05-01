"""
Test script for MemoryPatternAwareBehaviorLayer.
Validates deterministic behavior with clear, labeled test cases.
"""
from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer


def run_tests() -> None:
    """
    Run all test cases for MemoryPatternAwareBehaviorLayer.
    """

    # ── CASE 1: Empty patterns ────────────────────────────────
    input_data = {
        "intent": "greeting",
        "behavior": {"tone": "neutral"},
        "identity": {"patterns": {}}
    }

    result = MemoryPatternAwareBehaviorLayer.apply(input_data)
    print("CASE 1")
    print("INPUT:", input_data)
    print("OUTPUT:", result)
    print("-" * 50)

    # ── CASE 2: Single value (no decision possible) ───────────
    input_data = {
        "intent": "greeting",
        "behavior": {"tone": "neutral"},
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {
                        "formal": 5.0
                    }
                }
            }
        }
    }

    result = MemoryPatternAwareBehaviorLayer.apply(input_data)
    print("CASE 2")
    print("INPUT:", input_data)
    print("OUTPUT:", result)
    print("-" * 50)

    # ── CASE 3: Close values (no dominance) ───────────────────
    input_data = {
        "intent": "greeting",
        "behavior": {"tone": "neutral"},
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {
                        "formal": 5.0,
                        "casual": 4.5
                    }
                }
            }
        }
    }

    result = MemoryPatternAwareBehaviorLayer.apply(input_data)
    print("CASE 3")
    print("INPUT:", input_data)
    print("OUTPUT:", result)
    print("-" * 50)

    # ── CASE 4: Clear dominance ───────────────────────────────
    input_data = {
        "intent": "greeting",
        "behavior": {"tone": "neutral"},
        "identity": {
            "patterns": {
                "tone": {
                    "greeting": {
                        "formal": 6.0,
                        "casual": 2.0
                    }
                }
            }
        }
    }

    result = MemoryPatternAwareBehaviorLayer.apply(input_data)
    print("CASE 4")
    print("INPUT:", input_data)
    print("OUTPUT:", result)
    print("-" * 50)


if __name__ == "__main__":
    run_tests()
