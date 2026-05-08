"""
Simulate conflicting signals across intents and global patterns to evaluate system coherence.
"""

from core.memory_pattern_integrator import MemoryPatternIntegrator
from core.memory_pattern_decay_layer import MemoryPatternDecayLayer
from core.memory_global_pattern_layer import MemoryGlobalPatternLayer
from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer

integrator = MemoryPatternIntegrator()
decay_layer = MemoryPatternDecayLayer()
global_layer = MemoryGlobalPatternLayer()
behavior_layer = MemoryPatternAwareBehaviorLayer()


def run_cycle(identity, intent, tone):

    # 1. Create signal
    signal = {
        "type": "tone",
        "value": tone,
        "intent": intent,
        "weight": 1.0
    }

    # 2. Integrate
    identity = integrator.integrate({
        "pattern_signals": [signal],
        "identity": identity
    })["identity"]

    # 3. Decay
    identity = decay_layer.apply({"identity": identity})["identity"]

    # 4. Global aggregation
    identity = global_layer.apply({"identity": identity})["identity"]

    # 5. Apply behavior
    behavior_input = {"tone": tone}

    adjusted = behavior_layer.apply({
        "intent": intent,
        "behavior": behavior_input,
        "identity": identity
    })["behavior"]

    return identity, adjusted


def run_test():

    identity = {"patterns": {}}

    print("\nPHASE 1 -- DEBUG to technical (strong)\n")

    # Strong technical signal in debug
    for i in range(6):
        identity, adjusted = run_cycle(identity, "debug", "technical")

        print(f"[DEBUG CYCLE {i+1}]")
        print("Adjusted:", adjusted)
        print("Global:", identity.get("global_patterns"))
        print("-" * 40)

    print("\nPHASE 2 -- GREETING to casual (medium)\n")

    # Medium casual signal in greeting
    for i in range(4):
        identity, adjusted = run_cycle(identity, "greeting", "casual")

        print(f"[GREETING CYCLE {i+1}]")
        print("Adjusted:", adjusted)
        print("Global:", identity.get("global_patterns"))
        print("-" * 40)

    print("\nPHASE 3 -- TEST CONFLICT (greeting intent)\n")

    # Now test greeting behavior under conflict
    for i in range(5):
        behavior_input = {"tone": "neutral"}

        adjusted = behavior_layer.apply({
            "intent": "greeting",
            "behavior": behavior_input,
            "identity": identity
        })["behavior"]

        print(f"[CONFLICT TEST {i+1}]")
        print("Input:", behavior_input)
        print("Adjusted:", adjusted)
        print("Intent patterns:", identity["patterns"].get("tone", {}).get("greeting", {}))
        print("Global patterns:", identity.get("global_patterns", {}).get("tone", {}))
        print("-" * 40)


if __name__ == "__main__":
    run_test()
