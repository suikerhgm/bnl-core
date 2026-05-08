"""
Simulate multiple cycles of behavior → feedback → integration → decay → behavior adjustment.
"""

from core.memory_pattern_integrator import MemoryPatternIntegrator
from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer
from core.memory_pattern_decay_layer import MemoryPatternDecayLayer

integrator = MemoryPatternIntegrator()
behavior_layer = MemoryPatternAwareBehaviorLayer()
decay_layer = MemoryPatternDecayLayer()

intent = "greeting"


def simulate_cycle(identity, behavior_input):

    # Step 1: simulate feedback signal manually
    signal = {
        "type": "tone",
        "value": behavior_input["tone"],
        "intent": intent,
        "weight": 1.0
    }

    # Step 2: integrate
    result = integrator.integrate({
        "pattern_signals": [signal],
        "identity": identity
    })
    identity = result["identity"]

    # Step 3: decay
    identity = decay_layer.apply({"identity": identity})["identity"]

    # Step 4: apply pattern-aware behavior
    adjusted = behavior_layer.apply({
        "intent": intent,
        "behavior": behavior_input,
        "identity": identity
    })["behavior"]

    return identity, adjusted


def run():

    identity = {"patterns": {}}

    print("\nPHASE 1 — formal dominance\n")

    # First 5 cycles → formal
    for i in range(5):
        behavior = {"tone": "formal"}
        identity, adjusted = simulate_cycle(identity, behavior)

        print(f"Cycle {i+1}")
        print("Behavior:", behavior)
        print("Adjusted:", adjusted)
        print("Patterns:", identity["patterns"])
        print("-" * 40)

    print("\nPHASE 2 — switch to casual\n")

    # Next 5 cycles → casual
    for i in range(5):
        behavior = {"tone": "casual"}
        identity, adjusted = simulate_cycle(identity, behavior)

        print(f"Cycle {i+6}")
        print("Behavior:", behavior)
        print("Adjusted:", adjusted)
        print("Patterns:", identity["patterns"])
        print("-" * 40)


if __name__ == "__main__":
    run()
