"""
MemoryStabilityGuardLayer

Prevents unstable or noisy strategy adjustments by requiring:
  - Minimum data per source (total >= 5)
  - Stability threshold per source (total >= 10)
  - Accuracy change noise gate (bonus): skip if delta < 0.05

Fully deterministic — no randomness, no AI, no side effects.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryStabilityGuardLayer:
    """
    Guards strategy updates based on data stability.

    Input:
        {
            "performance_state": dict,  # {"source": {"correct": int, "total": int}}
            "config": dict,             # {"previous_accuracy": {...}} optional
        }

    Output:
        {"allow_update": bool}

    Rules (all must pass for allow_update=True):
      1. Minimum data: every tracked source has total >= MIN_TOTAL (5)
      2. Stability: every tracked source has total >= STABLE_TOTAL (10)
      3. Noise gate (bonus): if config includes previous_accuracy,
         abs(current - previous) for any changed source must be >= MIN_DELTA (0.05)
    """

    TRACKED_SOURCES = ("intent", "global", "conflict")

    # ── Thresholds ────────────────────────────────────────────────────
    MIN_TOTAL = 5          # Absolute minimum data points per source
    STABLE_TOTAL = 10      # Required for stability
    MIN_DELTA = 0.05       # Minimum accuracy change to consider meaningful

    def apply(self, input_data: dict) -> Dict[str, bool]:
        """
        Determine whether strategy updates should be allowed.

        Args:
            input_data: dict with "performance_state" and optionally "config".

        Returns:
            {"allow_update": bool}
        """
        if not isinstance(input_data, dict):
            return {"allow_update": False}

        performance_state = input_data.get("performance_state", {})
        config = input_data.get("config", {})

        if not isinstance(performance_state, dict):
            return {"allow_update": False}

        if not isinstance(config, dict):
            config = {}

        # ── Rule 1: Minimum data (every source must have total >= 5) ──
        for source in MemoryStabilityGuardLayer.TRACKED_SOURCES:
            entry = performance_state.get(source)
            if not isinstance(entry, dict):
                return {"allow_update": False}

            total = entry.get("total", 0)
            if not isinstance(total, int) or total < MemoryStabilityGuardLayer.MIN_TOTAL:
                return {"allow_update": False}

        # ── Rule 2: Stability (every source must have total >= 10) ────
        for source in MemoryStabilityGuardLayer.TRACKED_SOURCES:
            entry = performance_state.get(source)
            total = entry.get("total", 0)
            if total < MemoryStabilityGuardLayer.STABLE_TOTAL:
                return {"allow_update": False}

        # ── Rule 3 (bonus): Accuracy change noise gate ────────────────
        previous_accuracy = config.get("previous_accuracy", {})
        if isinstance(previous_accuracy, dict) and len(previous_accuracy) > 0:
            for source in MemoryStabilityGuardLayer.TRACKED_SOURCES:
                entry = performance_state.get(source)
                correct = entry.get("correct", 0)
                total = entry.get("total", 0)

                if total <= 0:
                    continue

                current_acc = correct / total
                prev_acc = previous_accuracy.get(source)

                if isinstance(prev_acc, (int, float)):
                    delta = abs(current_acc - prev_acc)
                    if delta < MemoryStabilityGuardLayer.MIN_DELTA:
                        return {"allow_update": False}

        # All checks passed
        return {"allow_update": True}
