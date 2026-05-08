"""
Validate that dynamic distribution factor behaves correctly for different signal shapes:
- peak dominant (one value much higher than others)
- distributed signal (many competing values)
- global peak vs distributed intent
- extreme spread (many equal values)
"""

from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer
from core.memory_conflict_resolution_layer import MemoryConflictResolutionLayer

behavior_layer = MemoryPatternAwareBehaviorLayer()
conflict_layer = MemoryConflictResolutionLayer()


def apply(identity, intent="greeting"):
    behavior = {"tone": "neutral"}

    behavior = behavior_layer.apply({
        "intent": intent,
        "behavior": behavior,
        "identity": identity
    })["behavior"]

    behavior = conflict_layer.apply({
        "intent": intent,
        "behavior": behavior,
        "identity": identity
    })["behavior"]

    return behavior


def run():

    print("\n=== CASE 1: PEAK DOMINANT ===\n")
    identity = {
        "patterns": {
            "tone": {
                "greeting": {
                    "casual": 10.0,
                    "formal": 1.0,
                    "technical": 1.0
                }
            }
        },
        "global_patterns": {
            "tone": {
                "casual": 3.0,
                "formal": 2.5
            }
        }
    }

    print("Expected: casual dominates strongly")
    print("Result:", apply(identity))

    print("\n=== CASE 2: DISTRIBUTED SIGNAL ===\n")
    identity = {
        "patterns": {
            "tone": {
                "greeting": {
                    "casual": 4.0,
                    "formal": 3.8,
                    "technical": 3.6
                }
            }
        },
        "global_patterns": {
            "tone": {
                "technical": 4.0,
                "casual": 3.5
            }
        }
    }

    print("Expected: distribution matters more")
    print("Result:", apply(identity))

    print("\n=== CASE 3: GLOBAL PEAK VS DISTRIBUTED INTENT ===\n")
    identity = {
        "patterns": {
            "tone": {
                "greeting": {
                    "casual": 3.0,
                    "formal": 3.0,
                    "technical": 3.0
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

    print("Expected: technical may dominate")
    print("Result:", apply(identity))

    print("\n=== CASE 4: EXTREME SPREAD ===\n")
    identity = {
        "patterns": {
            "tone": {
                "greeting": {
                    "a": 1.0,
                    "b": 1.0,
                    "c": 1.0,
                    "d": 1.0,
                    "e": 1.0
                }
            }
        },
        "global_patterns": {
            "tone": {
                "technical": 5.0,
                "casual": 4.8
            }
        }
    }

    print("Expected: distribution heavily influences result")
    print("Result:", apply(identity))


if __name__ == "__main__":
    run()
