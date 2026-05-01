"""
MemoryConflictResolutionLayer

Resolves conflicts between intent-based patterns and global patterns
when no single source has clear dominance.

Fully deterministic — no randomness, no timestamps, no real-time logic.
"""

import copy
from typing import Dict, List


class MemoryConflictResolutionLayer:
    """
    Combines intent and global pattern evidence when neither source
    has sufficient dominance alone, using adaptive source weighting
    based on signal strength.
    """

    DIMENSIONS = ("tone", "depth", "style")

    DOMINANCE_THRESHOLD = 1.3

    @staticmethod
    def _empty_dim_meta() -> dict:
        """Return a safe empty per-dimension metadata entry."""
        return {
            "source": "none",
            "intent_strength": 0.0,
            "global_strength": 0.0,
            "top_score": 0.0,
            "second_score": 0.0,
        }

    def apply(self, input_data: dict) -> dict:
        """
        Resolve behavior conflicts by combining weak signals.

        Args:
            input_data: dict with "intent", "behavior", "identity".

        Returns:
            dict with potentially adjusted "behavior".
        """
        if not isinstance(input_data, dict):
            return {"behavior": {}}

        intent = input_data.get("intent", "")
        behavior = input_data.get("behavior", {})
        identity = input_data.get("identity", {})

        if not isinstance(intent, str) or not intent.strip():
            return {"behavior": behavior}

        if not isinstance(behavior, dict):
            behavior = {}

        if not isinstance(identity, dict):
            return {"behavior": behavior}

        # Deep-copy to avoid mutating the original
        adjusted = copy.deepcopy(behavior)

        patterns = identity.get("patterns", {})
        global_patterns = identity.get("global_patterns", {})

        if not isinstance(patterns, dict) or not isinstance(global_patterns, dict):
            return {"behavior": adjusted}

        # ── Inicializar metadata por dimensión ──────────────────
        dimensions_meta: Dict[str, dict] = {}
        for dim in MemoryConflictResolutionLayer.DIMENSIONS:
            dimensions_meta[dim] = MemoryConflictResolutionLayer._empty_dim_meta()

        for dimension in MemoryConflictResolutionLayer.DIMENSIONS:

            # ── Only resolve if no strong decision was made ──
            if adjusted.get(dimension) != behavior.get(dimension):
                continue

            # ── Extract intent patterns for this intent ──
            by_dimension = patterns.get(dimension, {})
            if not isinstance(by_dimension, dict):
                continue

            intent_values = by_dimension.get(intent, {})
            if not isinstance(intent_values, dict):
                continue

            # ── Extract global patterns ──
            global_dim = global_patterns.get(dimension, {})
            if not isinstance(global_dim, dict):
                continue

            # ── Both must exist and have at least 2 values each ──
            if len(intent_values) < 2 or len(global_dim) < 2:
                continue

            # ── Filter intent values (minimal: key + type only) ──
            filtered_intent: Dict[str, float] = {}
            for val, w in intent_values.items():
                if isinstance(val, str) and val.strip():
                    if isinstance(w, bool):
                        continue
                    if isinstance(w, (int, float)):
                        filtered_intent[val.strip()] = float(w)

            if len(filtered_intent) < 2:
                continue

            # ── Filter global values (minimal: key + type only) ──
            filtered_global: Dict[str, float] = {}
            for val, w in global_dim.items():
                if isinstance(val, str) and val.strip():
                    if isinstance(w, bool):
                        continue
                    if isinstance(w, (int, float)):
                        filtered_global[val.strip()] = float(w)

            if len(filtered_global) < 2:
                continue

            # ── Compute hybrid strength: peak + dynamic distribution ──
            intent_vals: List[float] = list(filtered_intent.values())
            intent_max = max(intent_vals)
            intent_sum = sum(intent_vals)

            global_vals: List[float] = list(filtered_global.values())
            global_max = max(global_vals)
            global_sum = sum(global_vals)

            # Dynamic distribution factor: wider spread → more weight to distribution
            intent_spread = intent_sum / (intent_max + 1e-6)
            global_spread = global_sum / (global_max + 1e-6)

            intent_distribution_factor = min(0.5, intent_spread * 0.2)
            global_distribution_factor = min(0.5, global_spread * 0.2)

            intent_strength = intent_max + (intent_sum * intent_distribution_factor)
            global_strength = global_max + (global_sum * global_distribution_factor)
            total = intent_strength + global_strength

            if total <= 0.0:
                continue

            intent_weight = intent_strength / total
            global_weight = global_strength / total

            # ── Compute combined scores ──
            combined: Dict[str, float] = {}
            all_values = set(filtered_intent.keys()) | set(filtered_global.keys())

            for val in all_values:
                intent_score = max(filtered_intent.get(val, 0.0), 0.0)
                global_score = max(filtered_global.get(val, 0.0), 0.0)
                combined[val] = (intent_score * intent_weight) + (global_score * global_weight)

            # ── Sort by combined score descending ──
            sorted_combined = sorted(
                combined.items(), key=lambda x: x[1], reverse=True
            )

            if len(sorted_combined) < 2:
                continue

            top_value, top_score = sorted_combined[0]
            second_value, second_score = sorted_combined[1]

            # ── Apply softer dominance rule (1.3x) ──
            if second_score <= 0:
                continue

            if top_score < (second_score * MemoryConflictResolutionLayer.DOMINANCE_THRESHOLD):
                continue

            # ── Only apply if different from current ──
            if adjusted.get(dimension) == top_value:
                continue

            adjusted[dimension] = top_value

            # ── Update per-dimension metadata (conflict source) ──
            dimensions_meta[dimension] = {
                "source": "conflict",
                "intent_strength": intent_strength,
                "global_strength": global_strength,
                "top_score": top_score,
                "second_score": second_score,
            }

        return {"behavior": adjusted, "metadata": {"dimensions": dimensions_meta}}
