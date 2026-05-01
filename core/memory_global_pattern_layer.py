"""
MemoryGlobalPatternLayer

Aggregates identity["patterns"] into global patterns across all intents.

Fully deterministic — no randomness, no timestamps, no real-time logic.
Does NOT modify identity["patterns"].
"""

import copy
import math


class MemoryGlobalPatternLayer:
    """
    A deterministic layer that sums pattern weights across all intents
    per dimension and stores the result in identity["global_patterns"].
    """

    def apply(self, input_data: dict) -> dict:
        """
        Aggregate all pattern weights into global_patterns.

        Args:
            input_data: dict with optional "identity" key.

        Returns:
            dict with the same structure plus identity["global_patterns"].
        """
        if not isinstance(input_data, dict):
            return {"identity": {}}

        identity = input_data.get("identity")

        if not isinstance(identity, dict):
            return {"identity": {}}

        # Deep-copy to avoid mutating the original
        identity = copy.deepcopy(identity)

        patterns = identity.get("patterns", {})

        if not isinstance(patterns, dict):
            # Still set global_patterns to empty dict
            identity["global_patterns"] = {}
            return {"identity": identity}

        global_patterns = {}

        for dimension, intents in patterns.items():
            if not isinstance(intents, dict):
                continue

            for intent, values in intents.items():
                if not isinstance(values, dict):
                    continue

                for value, weight in values.items():
                    # Strict numeric validation
                    if isinstance(weight, (int, float)):
                        weight = float(weight)

                        if weight <= 0:
                            continue

                        if math.isnan(weight) or math.isinf(weight):
                            continue
                    else:
                        continue

                    # Ensure dimension key exists
                    if dimension not in global_patterns:
                        global_patterns[dimension] = {}

                    # Accumulate
                    global_patterns[dimension][value] = (
                        global_patterns[dimension].get(value, 0) + weight
                    )

        identity["global_patterns"] = global_patterns

        return {"identity": identity}
