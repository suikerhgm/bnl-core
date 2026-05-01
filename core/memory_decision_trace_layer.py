"""
MemoryDecisionTraceLayer

Captures a structured trace of how a behavior decision was made
by recording per-dimension source, confidence, and signal strengths.

Fully deterministic — no randomness, no AI, no side effects.
"""

from typing import Any, Dict


class MemoryDecisionTraceLayer:
    """
    Records a structured decision trace from pipeline metadata.
    Safe against missing or malformed metadata.

    Metadata format expected:
        {"dimensions": {
            "tone": {"source": ..., "top_score": ..., "second_score": ...},
            "depth": {"source": ..., "top_score": ..., "second_score": ...},
            "style": {"source": ..., "top_score": ..., "second_score": ...}
        }}
    """

    DIMENSIONS = ("tone", "depth", "style")

    def apply(self, input_data: dict) -> dict:
        """
        Build a decision trace from pipeline inputs and metadata.

        Args:
            input_data: dict with keys:
                - "intent" (str): the active intent.
                - "behavior_before" (dict): behavior before any layer applied.
                - "behavior_after" (dict): behavior after all layers applied.
                - "identity" (dict): identity (used only for structural safety).
                - "metadata" (dict): with "dimensions" key containing per-dimension metadata.

        Returns:
            dict with single key "decision_trace" containing the trace dict.
        """
        if not isinstance(input_data, dict):
            return {"decision_trace": self._empty_trace()}

        intent = input_data.get("intent", "")
        behavior_before = input_data.get("behavior_before", {})
        behavior_after = input_data.get("behavior_after", {})
        metadata = input_data.get("metadata", {})

        if not isinstance(intent, str):
            intent = ""

        if not isinstance(behavior_before, dict):
            behavior_before = {}

        if not isinstance(behavior_after, dict):
            behavior_after = {}

        if not isinstance(metadata, dict):
            metadata = {}

        changed = behavior_before != behavior_after

        # ── Extract per-dimension metadata ────────────────────────
        dimensions_raw = metadata.get("dimensions", {})
        if not isinstance(dimensions_raw, dict):
            dimensions_raw = {}

        # ── Determine overall source from dimensions ──────────────
        source = self._determine_overall_source(dimensions_raw, behavior_before, behavior_after)

        # ── Compute per-dimension confidence and aggregate ────────
        dimension_details: Dict[str, dict] = {}
        for dim in MemoryDecisionTraceLayer.DIMENSIONS:
            dim_meta = dimensions_raw.get(dim, {})
            if not isinstance(dim_meta, dict):
                dim_meta = {}

            dim_source = dim_meta.get("source", "none")
            dim_top = MemoryDecisionTraceLayer._safe_float(dim_meta.get("top_score"))
            dim_second = MemoryDecisionTraceLayer._safe_float(dim_meta.get("second_score"))
            dim_intent_strength = MemoryDecisionTraceLayer._safe_float(dim_meta.get("intent_strength"))
            dim_global_strength = MemoryDecisionTraceLayer._safe_float(dim_meta.get("global_strength"))

            dim_changed = behavior_before.get(dim) != behavior_after.get(dim)
            dim_confidence = MemoryDecisionTraceLayer._compute_dim_confidence(dim_source, dim_top, dim_second)

            dimension_details[dim] = {
                "source": dim_source if dim_changed else "none",
                "confidence": dim_confidence,
                "changed": dim_changed,
                "top_score": dim_top,
                "second_score": dim_second,
                "intent_strength": dim_intent_strength,
                "global_strength": dim_global_strength,
            }

        # ── Confidence by dimension (flat map) ──────────────────────
        confidence_by_dimension = {
            dim: dd["confidence"] for dim, dd in dimension_details.items()
        }

        # ── Compute overall confidence (max across changed dimensions) ──
        overall_confidence = 0.0
        for dd in dimension_details.values():
            if dd["changed"] and dd["confidence"] > overall_confidence:
                overall_confidence = dd["confidence"]

        # ── Aggregate signals across dimensions ────────────────────
        total_intent_strength = sum(
            dd["intent_strength"] for dd in dimension_details.values()
        )
        total_global_strength = sum(
            dd["global_strength"] for dd in dimension_details.values()
        )
        combined_used = any(
            dd["source"] == "conflict" for dd in dimension_details.values()
        )

        signals = {
            "intent_strength": total_intent_strength,
            "global_strength": total_global_strength,
            "combined_used": combined_used,
        }

        trace = {
            "intent": intent,
            "changed": changed,
            "before": dict(behavior_before),
            "after": dict(behavior_after),
            "source": source,
            "confidence": overall_confidence,
            "confidence_by_dimension": confidence_by_dimension,
            "signals": signals,
            "dimensions": dimension_details,
        }

        return {"decision_trace": trace}

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _empty_trace() -> dict:
        """Return a safe empty trace for malformed input."""
        return {
            "intent": "",
            "changed": False,
            "before": {},
            "after": {},
            "source": "none",
            "confidence": 0.0,
            "confidence_by_dimension": {"tone": 0.0, "depth": 0.0, "style": 0.0},
            "signals": {
                "intent_strength": 0.0,
                "global_strength": 0.0,
                "combined_used": False,
            },
            "dimensions": {
                dim: {
                    "source": "none",
                    "confidence": 0.0,
                    "changed": False,
                    "top_score": 0.0,
                    "second_score": 0.0,
                    "intent_strength": 0.0,
                    "global_strength": 0.0,
                }
                for dim in ("tone", "depth", "style")
            },

        }

    @staticmethod
    def _determine_overall_source(
        dimensions_raw: dict,
        behavior_before: dict,
        behavior_after: dict,
    ) -> str:
        """
        Determine overall source from per-dimension metadata.

        If all changed dimensions have the same source → that source.
        If mixed sources → "mixed".
        If no change → "none".
        """
        sources_found: set = set()
        for dim in MemoryDecisionTraceLayer.DIMENSIONS:
            if behavior_before.get(dim) != behavior_after.get(dim):
                dim_meta = dimensions_raw.get(dim, {})
                if isinstance(dim_meta, dict):
                    src = dim_meta.get("source", "none")
                    if src in ("intent", "global", "conflict"):
                        sources_found.add(src)

        if not sources_found:
            return "none"
        if len(sources_found) == 1:
            return sources_found.pop()
        return "mixed"

    @staticmethod
    def _compute_dim_confidence(source: str, top: float, second: float) -> float:
        """
        Compute confidence ratio for a single dimension.
        """
        if source == "none":
            return 0.0
        if second <= 0 or top <= 0:
            return 0.0
        return min(top / (second + 1e-6), 100.0)

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Safely coerce a value to float; return 0.0 on failure."""
        if value is None:
            return 0.0
        try:
            v = float(value)
            if v < 0:
                return 0.0
            return v
        except (ValueError, TypeError, OverflowError):
            return 0.0
