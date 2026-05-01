"""
MemoryPerformanceTracker

Tracks decision success rates per source (intent, global, conflict).
Maintains running counts of correct decisions and total attempts.

Fully deterministic — no randomness, no AI, no side effects.
"""

import copy
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryPerformanceTracker:
    """
    Tracks success rates per source for decision trace feedback.

    Input:
        {
            "decision_trace": dict,
            "feedback": bool,
            "state": dict,
        }

    Output:
        {"state": dict}

    State structure:
        {
            "intent":  {"correct": int, "total": int},
            "global":  {"correct": int, "total": int},
            "conflict": {"correct": int, "total": int},
        }
    """

    TRACKED_SOURCES = ("intent", "global", "conflict")

    def apply(self, input_data: dict) -> Dict[str, Any]:
        """
        Update performance tracking state from a single decision.

        Args:
            input_data: dict with "decision_trace", "feedback", "state".

        Returns:
            dict with "state" (updated tracking counters).
        """
        if not isinstance(input_data, dict):
            return {"state": {}}

        decision_trace = input_data.get("decision_trace", {})
        feedback = input_data.get("feedback", False)
        state = input_data.get("state", {})

        if not isinstance(decision_trace, dict):
            return {"state": state}

        if not isinstance(state, dict):
            state = {}

        if not isinstance(feedback, bool):
            feedback = False

        # Deep-copy to avoid mutating the original
        updated_state = copy.deepcopy(state)

        source = decision_trace.get("source", "")

        # Only track known sources
        if source not in MemoryPerformanceTracker.TRACKED_SOURCES:
            return {"state": updated_state}

        # Ensure source entry exists
        if source not in updated_state:
            updated_state[source] = {"correct": 0, "total": 0}

        entry = updated_state[source]

        # Validate existing entry structure
        if not isinstance(entry, dict):
            updated_state[source] = {"correct": 0, "total": 0}
            entry = updated_state[source]

        if not isinstance(entry.get("total"), int):
            entry["total"] = 0
        if not isinstance(entry.get("correct"), int):
            entry["correct"] = 0

        # Update counters
        entry["total"] += 1
        if feedback:
            entry["correct"] += 1

        return {"state": updated_state}
