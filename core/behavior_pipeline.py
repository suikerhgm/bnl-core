"""
BehaviorPipeline

Orquestra el pipeline completo de decisión de comportamiento:
1. MemoryPatternAwareBehaviorLayer — ajusta tono, depth, style por intent/global
2. MemoryConflictResolutionLayer — resuelve conflictos entre señales débiles
3. MemoryDecisionTraceLayer — captura traza estructurada de la decisión

Fully deterministic — sin AI, sin mutación de entrada.
"""

import copy
import logging
from typing import Any, Dict

from core.memory_pattern_aware_behavior_layer import MemoryPatternAwareBehaviorLayer
from core.memory_conflict_resolution_layer import MemoryConflictResolutionLayer
from core.memory_decision_trace_layer import MemoryDecisionTraceLayer

logger = logging.getLogger(__name__)


class BehaviorPipeline:
    """
    Pipeline completo de decisión de comportamiento.

    Retorna un dict con:
        - "behavior": dict con el comportamiento final ajustado
        - "decision_trace": dict con la traza estructurada de la decisión
    """

    DIMENSIONS = ("tone", "depth", "style")

    def __init__(self) -> None:
        self._behavior_layer = MemoryPatternAwareBehaviorLayer()
        self._conflict_layer = MemoryConflictResolutionLayer()
        self._trace_layer = MemoryDecisionTraceLayer()

    def run(
        self,
        intent: str,
        behavior: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Ejecuta el pipeline completo.

        Args:
            intent:   Intención actual (str).
            behavior: Comportamiento base (dict con claves como tone, depth, style).
            identity: Identidad con patrones acumulados (dict).

        Returns:
            Dict con:
                - "behavior": behavior final ajustado.
                - "decision_trace": traza de decisión.
        """
        # ── Validate inputs ──────────────────────────────────────
        if not isinstance(intent, str):
            intent = ""
        if not isinstance(behavior, dict):
            behavior = {}
        if not isinstance(identity, dict):
            identity = {}

        behavior_before = copy.deepcopy(behavior)

        # ── STEP 1: Behavior layer ───────────────────────────────
        input_data = {
            "intent": intent,
            "behavior": behavior,
            "identity": identity,
        }

        result = self._behavior_layer.apply(input_data)
        intermediate_behavior = result["behavior"]
        behavior_dim_meta = result.get("metadata", {}).get("dimensions", {})

        # ── STEP 2: Conflict resolution layer ────────────────────
        result = self._conflict_layer.apply({
            "intent": intent,
            "behavior": intermediate_behavior,
            "identity": identity,
        })
        final_behavior = result["behavior"]
        conflict_dim_meta = result.get("metadata", {}).get("dimensions", {})

        # ── Merge per-dimension: conflict overrides behavior for source="conflict" ──
        merged_dimensions = dict(behavior_dim_meta)
        for dim in BehaviorPipeline.DIMENSIONS:
            conflict_dim = conflict_dim_meta.get(dim, {})
            if isinstance(conflict_dim, dict) and conflict_dim.get("source") == "conflict":
                merged_dimensions[dim] = conflict_dim

        # ── STEP 3: Decision trace layer ─────────────────────────
        result = self._trace_layer.apply({
            "intent": intent,
            "behavior_before": behavior_before,
            "behavior_after": final_behavior,
            "identity": identity,
            "metadata": {"dimensions": merged_dimensions},
        })
        decision_trace = result["decision_trace"]

        return {
            "behavior": final_behavior,
            "decision_trace": decision_trace,
        }
