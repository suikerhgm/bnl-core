"""
test_learning_dynamics.py

Simulates long-term learning behavior using MemoryConfidenceFeedbackLayer.
Demonstrates reinforcement, penalization, and switching preferences across phases.
"""

from core.memory_confidence_feedback_layer import MemoryConfidenceFeedbackLayer

layer = MemoryConfidenceFeedbackLayer()

identity = {
    "patterns": {
        "tone": {
            "greeting": {
                "casual": 5.0,
                "formal": 5.0
            }
        }
    }
}


def simulate():
    global identity

    print("\n=== PHASE 1: REINFORCE CASUAL ===\n")

    for i in range(10):
        result = layer.apply({
            "decision_trace": {
                "intent": "greeting",
                "after": {"tone": "casual"},
                "dimensions": {
                    "tone": {
                        "source": "intent",
                        "changed": True,
                        "confidence": 2.0
                    }
                }
            },
            "feedback": True,
            "identity": identity
        })

        identity = result["identity"]
        print(f"Step {i+1}: {identity['patterns']['tone']['greeting']}")

    print("\n=== PHASE 2: PENALIZE CASUAL ===\n")

    for i in range(5):
        result = layer.apply({
            "decision_trace": {
                "intent": "greeting",
                "after": {"tone": "casual"},
                "dimensions": {
                    "tone": {
                        "source": "intent",
                        "changed": True,
                        "confidence": 2.0
                    }
                }
            },
            "feedback": False,
            "identity": identity
        })

        identity = result["identity"]
        print(f"Step {i+1}: {identity['patterns']['tone']['greeting']}")

    print("\n=== PHASE 3: SWITCH TO FORMAL ===\n")

    for i in range(10):
        result = layer.apply({
            "decision_trace": {
                "intent": "greeting",
                "after": {"tone": "formal"},
                "dimensions": {
                    "tone": {
                        "source": "intent",
                        "changed": True,
                        "confidence": 2.0
                    }
                }
            },
            "feedback": True,
            "identity": identity
        })

        identity = result["identity"]
        print(f"Step {i+1}: {identity['patterns']['tone']['greeting']}")


if __name__ == "__main__":
    simulate()
