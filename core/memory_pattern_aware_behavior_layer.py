"""
Capa de comportamiento consciente de patrones para Nexus BNL.
Ajusta el comportamiento actual usando patrones de identidad acumulados.
Determinista — sin AI, sin mutación de entrada, seguro ante entradas malformadas.
"""
import logging
import math
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryPatternAwareBehaviorLayer:
    """
    Capa que ajusta tono, profundidad y estilo del comportamiento
    basándose en patrones de identidad acumulados.

    Reglas:
        - No reemplaza la lógica de comportamiento existente.
        - Solo ajusta tone, depth, style si hay suficiente señal.
        - No modifica verbosity.
        - No muta input_data.
        - Determinista.
    """

    DIMENSIONS = ("tone", "depth", "style")

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

    @staticmethod
    def apply(input_data: dict) -> dict:
        """
        Ajusta el comportamiento usando patrones de identidad.

        Args:
            input_data: Dict con las claves:
                - "intent" (str): Intención actual.
                - "behavior" (dict): Comportamiento actual con claves
                    como "tone", "depth", "style", etc.
                - "identity" (dict): Identidad con patrones acumulados.

        Returns:
            Dict con "behavior" ajustado si hay suficiente señal.
        """
        intent: str = input_data.get("intent", "")
        behavior: Dict[str, Any] = input_data.get("behavior", {})
        identity: Dict[str, Any] = input_data.get("identity", {})

        # ── Validaciones de entrada ──────────────────────────────
        if not isinstance(intent, str) or not intent.strip():
            return {"behavior": behavior}

        if not isinstance(behavior, dict):
            behavior = {}

        if not isinstance(identity, dict):
            return {"behavior": behavior}

        # ── Trabajar sobre una copia para no mutar el original ───
        adjusted = dict(behavior)

        # ── Inicializar metadata por dimensión ──────────────────
        dimensions_meta: Dict[str, dict] = {}
        for dim in MemoryPatternAwareBehaviorLayer.DIMENSIONS:
            dimensions_meta[dim] = MemoryPatternAwareBehaviorLayer._empty_dim_meta()

        # ── Procesar cada dimensión ──────────────────────────────
        for dimension in MemoryPatternAwareBehaviorLayer.DIMENSIONS:
            # ── STEP 1: Extraer patrones de forma segura ─────────
            patterns_raw = identity.get("patterns", {})

            if not isinstance(patterns_raw, dict):
                continue

            by_dimension = patterns_raw.get(dimension, {})

            if not isinstance(by_dimension, dict):
                continue

            by_intent = by_dimension.get(intent, {})

            if not isinstance(by_intent, dict) or not by_intent:
                continue

            # ── STEP 2: Validar estructura y pesos ───────────────
            valid: Dict[str, float] = {}
            for val, w in by_intent.items():
                if not (isinstance(val, str) and val.strip()):
                    continue

                if not isinstance(w, (int, float)):
                    continue

                w = float(w)

                # FIX 1: Reject <= 0, NaN, Inf
                if w <= 0:
                    continue

                if math.isnan(w) or math.isinf(w):
                    continue

                valid[val.strip()] = w

            if not valid:
                continue

            # ── STEP 3: Ordenar valores por peso descendente ─────
            sorted_values = sorted(
                valid.items(), key=lambda x: x[1], reverse=True
            )

            # STEP 3b: Si hay menos de 2 valores → no hay suficiente señal
            if len(sorted_values) < 2:
                continue

            # ── STEP 4: Extraer top y segundo ────────────────────
            top_value, top_weight = sorted_values[0]
            second_value, second_weight = sorted_values[1]

            # FIX 2: Prevenir zero-dominance
            if second_weight <= 0:
                continue

            # ── STEP 5: Regla de dominancia relativa ─────────────
            if top_weight < (second_weight * 1.5):
                continue

            # ── STEP 5b: No ajustar si ya es el valor actual ────
            if dimension not in adjusted:
                continue

            if adjusted[dimension] == top_value:
                continue

            # ── STEP 6: Aplicar ajuste ───────────────────────────
            adjusted[dimension] = top_value

            # ── Update per-dimension metadata (intent source) ───
            dimensions_meta[dimension] = {
                "source": "intent",
                "intent_strength": top_weight,
                "global_strength": 0.0,
                "top_score": top_weight,
                "second_score": second_weight,
            }

            # Dimension was adjusted by intent logic → skip fallback
            continue

        # ── STEP 7: Fallback a patrones globales ───────────────
        # Se ejecuta para cada dimensión, solo si la lógica de intents
        # no realizó ningún cambio en esa dimensión.

        for dimension in MemoryPatternAwareBehaviorLayer.DIMENSIONS:
            # Solo aplicar fallback si la dimensión NO fue modificada
            if adjusted.get(dimension) != behavior.get(dimension):
                continue

            global_patterns = identity.get("global_patterns", {})

            if not isinstance(global_patterns, dict):
                continue

            global_dim = global_patterns.get(dimension, {})

            if not isinstance(global_dim, dict):
                continue

            if len(global_dim) < 2:
                continue

            # Ordenar valores por peso descendente
            sorted_global = sorted(
                global_dim.items(), key=lambda x: x[1], reverse=True
            )

            top_value_g, top_weight_g = sorted_global[0]
            second_value_g, second_weight_g = sorted_global[1]

            # Minimal safe normalization (upstream already validates)
            top_weight_g = float(top_weight_g)
            second_weight_g = float(second_weight_g)

            if second_weight_g <= 0:
                continue

            # Misma regla de dominancia relativa
            if top_weight_g < (second_weight_g * 1.5):
                continue

            # No ajustar si ya es el valor actual
            if adjusted.get(dimension) == top_value_g:
                continue

            # Aplicar ajuste global
            adjusted[dimension] = top_value_g

            # ── Update per-dimension metadata (global source) ───
            dimensions_meta[dimension] = {
                "source": "global",
                "intent_strength": 0.0,
                "global_strength": top_weight_g,
                "top_score": top_weight_g,
                "second_score": second_weight_g,
            }

        return {"behavior": adjusted, "metadata": {"dimensions": dimensions_meta}}
