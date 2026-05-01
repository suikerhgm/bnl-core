"""
MemoryPatternDecayLayer

Applies controlled, stable decay to identity patterns.

Fully deterministic — no randomness, no timestamps, no real-time logic.
"""

import copy

DECAY_FACTOR = 0.995
PRUNE_THRESHOLD = 0.05


class MemoryPatternDecayLayer:
    """
    A deterministic decay layer that gradually reduces pattern weights
    and prunes entries that fall below a minimum threshold.
    """

    def apply(self, input_data: dict) -> dict:
        """
        Apply decay to all numeric weights inside identity["patterns"].

        Args:
            input_data: dict with optional "identity" key.

        Returns:
            dict with the same structure, possibly pruned.
        """
        if not isinstance(input_data, dict):
            return {"identity": {}}

        identity = input_data.get("identity")

        if not isinstance(identity, dict):
            return {"identity": {}}

        # Deep-copy identity to avoid mutating the original
        identity = copy.deepcopy(identity)

        patterns = identity.get("patterns", {})

        if not isinstance(patterns, dict):
            return {"identity": identity}

        new_patterns = {}

        for dimension, intents in patterns.items():
            if not isinstance(intents, dict):
                continue

            new_intents = {}

            for intent, values in intents.items():
                if not isinstance(values, dict):
                    continue

                new_values = {}

                for key, weight in values.items():
                    # Validate numeric — bool is subclass of int, exclude explicitly
                    if isinstance(weight, bool):
                        continue
                    if not isinstance(weight, (int, float)):
                        continue

                    # Apply decay
                    new_weight = weight * DECAY_FACTOR

                    # Prune if below threshold
                    if new_weight < PRUNE_THRESHOLD:
                        continue

                    new_values[key] = new_weight

                # Clean empty branches: remove empty intent
                if new_values:
                    new_intents[intent] = new_values

            # Keep top-level dimension even if empty (DO NOT remove)
            new_patterns[dimension] = new_intents

        identity["patterns"] = new_patterns

        return {"identity": identity}
