"""
MemoryConfidenceFeedbackLayer

Adjust pattern strengths based on decision outcomes.
Reinforces or weakens patterns depending on whether the
decision was correct (feedback=True) or incorrect (feedback=False).

Fully deterministic — no randomness, no AI, no side effects.
"""

import copy
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryConfidenceFeedbackLayer:
    """
    Adjusts identity pattern weights based on decision trace and feedback.

    Input:
        {
            "decision_trace": dict,
            "feedback": bool,
            "identity": dict,
        }

    Output:
        {"identity": dict}

    Adjustment rules per changed dimension:
        feedback=True  → +0.2 (intent), +0.15 (conflict), +0.1 (global)
        feedback=False → -0.2 (intent), -0.15 (conflict), -0.1 (global)

    Only adjusts existing values — never creates new categories.
    Weights floored at 0 (no negatives).
    """

    # Adjustment magnitudes by source
    ADJUSTMENTS = {
        "intent": 0.2,
        "conflict": 0.15,
        "global": 0.1,
    }

    # Soft cap to prevent unbounded growth
    MAX_WEIGHT = 10.0

    DIMENSIONS = ("tone", "depth", "style")

    def apply(self, input_data: dict) -> Dict[str, Any]:
        """
        Apply confidence-based feedback to identity patterns.

        Args:
            input_data: dict with "decision_trace", "feedback", "identity".

        Returns:
            dict with "identity" (potentially adjusted).
        """
        if not isinstance(input_data, dict):
            return {"identity": {}}

        decision_trace = input_data.get("decision_trace", {})
        feedback = input_data.get("feedback", False)
        identity = input_data.get("identity", {})

        if not isinstance(decision_trace, dict):
            return {"identity": identity}

        if not isinstance(identity, dict):
            return {"identity": {}}

        if not isinstance(feedback, bool):
            feedback = False

        # Deep-copy to avoid mutating the original
        adjusted_identity = copy.deepcopy(identity)

        # Ensure patterns exists
        patterns = adjusted_identity.get("patterns", {})
        if not isinstance(patterns, dict):
            return {"identity": adjusted_identity}

        intent = decision_trace.get("intent", "")
        if not isinstance(intent, str) or not intent.strip():
            return {"identity": adjusted_identity}

        behavior_after = decision_trace.get("after", {})
        if not isinstance(behavior_after, dict):
            return {"identity": adjusted_identity}

        dimensions = decision_trace.get("dimensions", {})
        if not isinstance(dimensions, dict):
            return {"identity": adjusted_identity}

        # ── Process each dimension ────────────────────────────────
        for dimension in MemoryConfidenceFeedbackLayer.DIMENSIONS:
            dim_data = dimensions.get(dimension)
            if not isinstance(dim_data, dict):
                continue

            # Skip unchanged dimensions
            if not dim_data.get("changed", False):
                continue

            # Source determines base adjustment magnitude
            source = dim_data.get("source", "none")
            base_adjustment = MemoryConfidenceFeedbackLayer.ADJUSTMENTS.get(source)
            if base_adjustment is None:
                continue

            # Scale adjustment by confidence: full at confidence >= 2.0, proportional below
            confidence = dim_data.get("confidence", 0.0)
            if not isinstance(confidence, (int, float)):
                confidence = 0.0
            if confidence < 0:
                confidence = 0.0
            scale = min(1.0, confidence / 2.0)
            adjustment = base_adjustment * scale

            # Value that was set
            value = behavior_after.get(dimension)
            if not isinstance(value, str) or not value.strip():
                continue

            # Navigate: patterns[dimension][intent][value]
            by_dimension = patterns.get(dimension)
            if not isinstance(by_dimension, dict):
                continue

            by_intent = by_dimension.get(intent)
            if not isinstance(by_intent, dict):
                continue

            if value not in by_intent:
                continue

            current_weight = by_intent[value]
            if not isinstance(current_weight, (int, float)):
                continue

            # Apply feedback direction
            if feedback:
                current_weight += adjustment
            else:
                current_weight -= adjustment

            # Floor at 0
            if current_weight < 0:
                current_weight = 0.0

            # Soft cap to prevent runaway dominance
            current_weight = min(MemoryConfidenceFeedbackLayer.MAX_WEIGHT, current_weight)

            by_intent[value] = current_weight

        return {"identity": adjusted_identity}
