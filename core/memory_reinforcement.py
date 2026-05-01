"""
Capa de refuerzo de memoria para Nexus BNL.
Detecta memorias repetidas (misma key + mismo valor normalizado)
y registra señales de refuerzo en almacenamiento persistente.
Determinista — sin AI.
"""
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class MemoryReinforcementLayer:
    """
    Capa que refuerza memorias basadas en repetición.

    Se inserta entre MemorySelfCorrectionLayer y MemorySynthesizer.
    No modifica la estructura de datos retornada — solo registra
    señales de refuerzo en almacenamiento persistente.

    Reglas:
        - Agrupa por (key, normalized_value).
        - Ignora key="inference", status="deprecated", valores vacíos.
        - Si count >= 2, genera señal de refuerzo.
        - Refuerzo = min(3, count - 1).
        - Importance base = 5, capped en 10.
        - No duplica logs de refuerzo en la misma ejecución.
        - Falla silenciosamente.
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
    async def reinforce(
        cls,
        ranked_memories: List[Dict[str, Any]],
        memory_manager: Any,
    ) -> List[Dict[str, Any]]:
        """
        Refuerza memorias repetidas.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score".
            memory_manager:  Instancia de MemoryManager para persistencia.

        Returns:
            La misma lista original, sin modificar.
        """
        if not ranked_memories:
            return ranked_memories

        reinforced: set = set()

        # ── 1. Agrupar por (key, normalized_value) ──────────────────
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for item in ranked_memories:
            memory = item.get("memory", {})
            key = memory.get("key")

            if not key:
                continue
            if key == "inference":
                continue
            if memory.get("status") == "deprecated":
                continue

            raw = memory.get("value", "")
            if not raw:
                continue

            normalized = cls._normalize(raw)
            if not normalized:
                continue

            group_key = (key, normalized)
            groups.setdefault(group_key, []).append(item)

        # ── 2. Procesar grupos con repetición ──────────────────────
        for (key, normalized), items in groups.items():
            count = len(items)
            if count < 2:
                continue  # sin repetición

            if (key, normalized) in reinforced:
                continue  # ya registrado en esta ejecución

            reinforced.add((key, normalized))

            reinforcement = min(3, count - 1)
            base_importance = 5

            # Tomar el valor original (no normalizado) del primer item
            value = items[0].get("memory", {}).get("value", "")

            try:
                await memory_manager.save_episode(
                    content=(
                        f"[REINFORCEMENT] {key}: '{value}' "
                        f"reinforced (+{reinforcement})"
                    ),
                    summary=f"Refuerzo de memoria: {key}",
                    tags=[key, "memory_reinforcement", "system_event"],
                    importance=min(10, base_importance + reinforcement),
                )
                logger.info(
                    "[REINFORCEMENT] key=%s value=%s | count=%d reinforcement=+%d",
                    key, value, count, reinforcement,
                )
            except Exception as e:
                logger.warning(
                    "[REINFORCEMENT] FAILED key=%s value=%s: %s",
                    key, value, e,
                )

        return ranked_memories
