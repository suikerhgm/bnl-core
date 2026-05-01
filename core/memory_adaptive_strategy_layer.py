"""
MemoryAdaptiveStrategyLayer

Adjusts decision parameters dynamically based on performance metrics.
Uses accuracy per source to tune:
  - dominance_threshold: 1.1 – 2.0
  - intent_weight_factor: 0.1 – 1.0
  - global_weight_factor: 0.1 – 1.0

Fully deterministic — no randomness, no AI, no side effects.
"""

import copy
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryAdaptiveStrategyLayer:
    """
    Adjusts config parameters based on performance tracking data.

    Input:
        {
            "performance_state": dict,   # {"source": {"correct": int, "total": int}}
            "config": dict,              # {"dominance_threshold": float, ...}
        }

    Output:
        {"config": dict}

    Adjustment rules:
      1. intent accuracy > 0.7  → intent_weight_factor += 0.1
      2. global accuracy < 0.5  → global_weight_factor -= 0.1
      3. conflict accuracy > 0.8 → dominance_threshold -= 0.1

    All values clamped to defined bounds.
    """

    # ── Default config ────────────────────────────────────────────────
    DEFAULT_CONFIG = {
        "dominance_threshold": 1.5,
        "intent_weight_factor": 0.5,
        "global_weight_factor": 0.5,
    }

    # ── Clamp bounds ──────────────────────────────────────────────────
    DOMINANCE_MIN = 1.1
    DOMINANCE_MAX = 2.0
    WEIGHT_MIN = 0.1
    WEIGHT_MAX = 1.0

    # ── Adjustment amounts ────────────────────────────────────────────
    INTENT_BOOST = 0.1
    GLOBAL_PENALTY = 0.1
    DOMINANCE_REDUCTION = 0.1

    # ── Accuracy thresholds ───────────────────────────────────────────
    INTENT_ACCURACY_HIGH = 0.7
    GLOBAL_ACCURACY_LOW = 0.5
    CONFLICT_ACCURACY_HIGH = 0.8

    TRACKED_SOURCES = ("intent", "global", "conflict")

    def apply(self, input_data: dict) -> Dict[str, Any]:
        """
        Adjust config based on performance metrics.

        Args:
            input_data: dict with "performance_state" and "config".

        Returns:
            dict with "config" (potentially adjusted).
        """
        if not isinstance(input_data, dict):
            return {"config": dict(MemoryAdaptiveStrategyLayer.DEFAULT_CONFIG)}

        performance_state = input_data.get("performance_state", {})
        config = input_data.get("config", {})

        if not isinstance(performance_state, dict):
            performance_state = {}

        if not isinstance(config, dict):
            config = {}

        # Deep-copy to avoid mutating the original
        adjusted_config = copy.deepcopy(config)

        # Ensure all expected keys exist with defaults
        for key, default in MemoryAdaptiveStrategyLayer.DEFAULT_CONFIG.items():
            if key not in adjusted_config:
                adjusted_config[key] = default

        # ── Rule 1: Intent accuracy > 0.7 → boost intent_weight_factor ──
        intent_accuracy = self._get_accuracy(performance_state, "intent")
        if intent_accuracy is not None and intent_accuracy > MemoryAdaptiveStrategyLayer.INTENT_ACCURACY_HIGH:
            adjusted_config["intent_weight_factor"] += MemoryAdaptiveStrategyLayer.INTENT_BOOST

        # ── Rule 2: Global accuracy < 0.5 → penalize global_weight_factor ──
        global_accuracy = self._get_accuracy(performance_state, "global")
        if global_accuracy is not None and global_accuracy < MemoryAdaptiveStrategyLayer.GLOBAL_ACCURACY_LOW:
            adjusted_config["global_weight_factor"] -= MemoryAdaptiveStrategyLayer.GLOBAL_PENALTY

        # ── Rule 3: Conflict accuracy > 0.8 → lower dominance_threshold ──
        conflict_accuracy = self._get_accuracy(performance_state, "conflict")
        if conflict_accuracy is not None and conflict_accuracy > MemoryAdaptiveStrategyLayer.CONFLICT_ACCURACY_HIGH:
            adjusted_config["dominance_threshold"] -= MemoryAdaptiveStrategyLayer.DOMINANCE_REDUCTION

        # ── Clamp all values ──────────────────────────────────────────
        adjusted_config["dominance_threshold"] = max(
            MemoryAdaptiveStrategyLayer.DOMINANCE_MIN,
            min(MemoryAdaptiveStrategyLayer.DOMINANCE_MAX, adjusted_config["dominance_threshold"]),
        )
        adjusted_config["intent_weight_factor"] = max(
            MemoryAdaptiveStrategyLayer.WEIGHT_MIN,
            min(MemoryAdaptiveStrategyLayer.WEIGHT_MAX, adjusted_config["intent_weight_factor"]),
        )
        adjusted_config["global_weight_factor"] = max(
            MemoryAdaptiveStrategyLayer.WEIGHT_MIN,
            min(MemoryAdaptiveStrategyLayer.WEIGHT_MAX, adjusted_config["global_weight_factor"]),
        )

        return {"config": adjusted_config}

    def _get_accuracy(self, performance_state: dict, source: str) -> float | None:
        """
        Compute accuracy for a given source.
        Returns None if the source is missing or has no data.
        """
        entry = performance_state.get(source)
        if not isinstance(entry, dict):
            return None

        total = entry.get("total", 0)
        correct = entry.get("correct", 0)

        if not isinstance(total, int) or not isinstance(correct, int):
            return None

        if total <= 0:
            return None

        return correct / total
