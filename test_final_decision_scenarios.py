"""
Validate full system behavior across multiple decision scenarios:
- strong intent + weak global
- weak intent + strong global
- both medium
- contradictory signals
"""

from core.memory_pattern_integrator import MemoryPatternIntegrator
from core.memory_pattern_decay_layer import MemoryPatternDecayLayer
from core.memory_global_pattern_layer import MemoryGlobalPatternLayer
from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer
from core.memory_conflict_resolution_layer import MemoryConflictResolutionLayer

integrator = MemoryPatternIntegrator()
decay_layer = MemoryPatternDecayLayer()
global_layer = MemoryGlobalPatternLayer()
behavior_layer = MemoryPatternAwareBehaviorLayer()
conflict_layer = MemoryConflictResolutionLayer()


def apply_full_pipeline(identity, intent, behavior_input):

    # Apply behavior layer (intent + global fallback)
    result = behavior_layer.apply({
        "intent": intent,
        "behavior": behavior_input,
        "identity": identity
    })
    behavior = result["behavior"]

    # Apply conflict resolution
    result = conflict_layer.apply({
        "intent": intent,
        "behavior": behavior,
        "identity": identity
    })

    return result["behavior"]


def build_identity(intent_data, global_data):
    return {
        "patterns": {
            "tone": intent_data
        },
        "global_patterns": {
            "tone": global_data
        }
    }


def run_scenario(name, intent, intent_data, global_data):

    identity = build_identity(intent_data, global_data)

    print(f"\n=== {name} ===\n")

    for i in range(3):
        behavior_input = {"tone": "neutral"}

        result = apply_full_pipeline(identity, intent, behavior_input)

        print(f"Run {i+1}")
        print("Input:", behavior_input)
        print("Output:", result)
        print("Intent:", intent_data.get(intent, {}))
        print("Global:", global_data)
        print("-" * 40)


def run():

    # 1. Strong intent + weak global
    run_scenario(
        "STRONG INTENT + WEAK GLOBAL",
        "greeting",
        {
            "greeting": {
                "casual": 6.0,
                "formal": 2.0
            }
        },
        {
            "casual": 2.0,
            "formal": 1.5
        }
    )

    # 2. Weak intent + strong global
    run_scenario(
        "WEAK INTENT + STRONG GLOBAL",
        "greeting",
        {
            "greeting": {
                "casual": 2.5,
                "formal": 2.2
            }
        },
        {
            "technical": 8.0,
            "casual": 2.0
        }
    )

    # 3. Both medium
    run_scenario(
        "BOTH MEDIUM",
        "greeting",
        {
            "greeting": {
                "casual": 3.0,
                "formal": 2.8
            }
        },
        {
            "technical": 3.2,
            "casual": 3.0
        }
    )

    # 4. Contradictory signals
    run_scenario(
        "CONTRADICTORY",
        "greeting",
        {
            "greeting": {
                "casual": 4.0,
                "formal": 3.8
            }
        },
        {
            "technical": 6.0,
            "casual": 2.5
        }
    )


if __name__ == "__main__":
    run()
