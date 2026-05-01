"""
Capa de auto-corrección de memoria para Nexus BNL.
Detecta conflictos entre memorias con la misma key y diferentes valores,
marca las incorrectas como deprecated en almacenamiento persistente
y registra el historial de corrección.
Determinista — sin AI.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MemorySelfCorrectionLayer:
    """
    Capa que detecta y corrige conflictos entre memorias persistentes.

    Se inserta entre MemoryInference y MemorySynthesizer.
    No modifica la estructura de datos retornada — solo aplica correcciones
    en almacenamiento persistente.

    Reglas:
        - Agrupa por key.
        - Ignora memorias sintéticas (key="inference").
        - Ignora memorias ya deprecated.
        - Dentro de cada grupo con valores distintos, elige el de mayor score.
        - Solo corrige si la diferencia de score >= 2.
        - Depreca los perdedores vía memory_manager.deprecate_memory().
        - Registra una entrada de corrección vía memory_manager.save_episode().
        - Falla silenciosamente: nunca interrumpe el pipeline.
        - Es idempotente: no re-corrige pares (key, value) ya corregidos.
    """

    @staticmethod
    def _normalize(value: str) -> str:
        """Normaliza un valor para comparación determinista."""
        normalized = value.lower().strip()
        normalized = normalized.replace(".", "").replace(",", "")
        normalized = normalized.replace("-", " ")
        normalized = " ".join(normalized.split())
        return normalized

    @classmethod
    async def correct(
        cls,
        ranked_memories: List[Dict[str, Any]],
        memory_manager: Any,
    ) -> List[Dict[str, Any]]:
        """
        Corrige conflictos en memorias persistentes.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score".
            memory_manager:  Instancia de MemoryManager para persistencia.

        Returns:
            La misma lista original, sin modificar.
        """
        if not ranked_memories:
            return ranked_memories

        corrected: set = set()

        # ── 1. Agrupar por key, filtrando no elegibles ────────────────
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in ranked_memories:
            memory = item.get("memory", {})
            key = memory.get("key")

            # Ignorar memorias sin key
            if not key:
                continue

            # Ignorar memorias sintéticas (generadas por inference)
            if key == "inference":
                continue

            # Ignorar memorias ya deprecated
            if memory.get("status") == "deprecated":
                continue

            # Ignorar valores vacíos
            raw = memory.get("value", "")
            if not raw:
                continue

            groups.setdefault(key, []).append(item)

        # ── 2. Procesar cada grupo con conflictos ─────────────────────
        for key, items in groups.items():
            if len(items) <= 1:
                continue  # sin conflicto

            # Extraer valores normalizados
            entries = []
            for item in items:
                memory = item.get("memory", {})
                raw = memory.get("value", "")
                normalized = cls._normalize(raw)
                if not normalized:
                    continue
                entries.append((normalized, item))

            if len(entries) <= 1:
                continue

            unique_values = {e[0] for e in entries}
            if len(unique_values) <= 1:
                continue  # todos iguales — sin conflicto

            # ── 3. Ordenar por score descendente ─────────────────────
            sorted_entries = sorted(
                entries,
                key=lambda x: x[1].get("score", 0),
                reverse=True,
            )
            winner_normalized, winner_item = sorted_entries[0]
            winner_score = winner_item.get("score", 0)
            winner_value = winner_item.get("memory", {}).get("value", "")

            # ── 4. Deprecar los perdedores ───────────────────────────
            for normalized, item in sorted_entries[1:]:
                memory = item.get("memory", {})
                value = memory.get("value", "")
                loser_score = item.get("score", 0)

                if normalized == winner_normalized:
                    continue  # mismo valor normalizado

                # Score gap protection: no corregir si diferencia < 2
                if (winner_score - loser_score) < 2:
                    logger.info(
                        "[SELF-CORRECTION] key=%s | SKIP (score gap too small: "
                        "winner=%d loser=%d) | old=%s new=%s",
                        key, winner_score, loser_score, value, winner_value,
                    )
                    continue

                correction_key = (key, normalized)
                if correction_key in corrected:
                    continue  # ya corregido en esta ejecución

                corrected.add(correction_key)

                try:
                    await memory_manager.deprecate_memory(key, value)
                    await memory_manager.save_episode(
                        content=(
                            f"Auto-correction: key '{key}' changed "
                            f"from '{value}' to '{winner_value}'"
                        ),
                        summary=f"Corrección: {key}",
                        tags=[key, "memory_correction", "system_event"],
                        importance=7,
                    )
                    logger.info(
                        "[SELF-CORRECTION] key=%s | old=%s new=%s | "
                        "winner_score=%d loser_score=%d",
                        key, value, winner_value, winner_score, loser_score,
                    )
                except Exception as e:
                    logger.warning(
                        "[SELF-CORRECTION] FAILED key=%s value=%s: %s",
                        key, value, e,
                    )

        return ranked_memories
