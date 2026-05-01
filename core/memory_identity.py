"""
Capa de identidad de memoria para Nexus BNL.
Detecta patrones reforzados y los convierte en señales de identidad.
Determinista — sin AI, sin persistencia, sin mutación.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MemoryIdentityLayer:
    """
    Capa que construye un perfil de identidad a partir de memorias.

    Se inserta entre MemoryReinforcementLayer y MemorySynthesizer.
    No modifica los datos de entrada — retorna un dict de identidad nuevo.

    Estructura de identidad:
        {
            "user_name": str | None,
            "project_name": str | None,
            "goals": List[str],
            "interests": List[str],
            "patterns": List[str]
        }
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
    def build_identity(cls, ranked_memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construye un perfil de identidad a partir de memorias rankeadas.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score".

        Returns:
            Dict con la identidad del usuario.
        """
        identity: Dict[str, Any] = {
            "user_name": None,
            "project_name": None,
            "goals": [],
            "interests": [],
            "patterns": [],
        }

        if not ranked_memories:
            return identity

        # ── 1. Filtrar y agrupar memorias elegibles ────────────────
        eligible: List[Dict[str, Any]] = []
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

            eligible.append(item)

        if not eligible:
            return identity

        # ── 2. Extraer user_name (primero) ─────────────────────────
        for item in eligible:
            memory = item.get("memory", {})
            if memory.get("key") == "user_name":
                identity["user_name"] = memory.get("value", "")
                break

        # ── 3. Extraer project_name (primero) ──────────────────────
        for item in eligible:
            memory = item.get("memory", {})
            if memory.get("key") == "project_name":
                identity["project_name"] = memory.get("value", "")
                break

        # ── 4. Extraer goals (top 2 por score) ─────────────────────
        goals = []
        for item in eligible:
            memory = item.get("memory", {})
            if memory.get("key") == "goal":
                goals.append((item.get("score", 0), memory.get("value", "")))
        goals.sort(key=lambda x: x[0], reverse=True)
        identity["goals"] = [v for _, v in goals[:2]]

        # ── 5. Extraer interests (score >= 8, top 3) ───────────────
        interest_keys = {"user_name", "project_name", "goal"}
        interests = []
        for item in eligible:
            memory = item.get("memory", {})
            key = memory.get("key", "")
            score = item.get("score", 0)
            if key not in interest_keys and score >= 8:
                interests.append((score, memory.get("value", "")))
        interests.sort(key=lambda x: x[0], reverse=True)
        identity["interests"] = [v for _, v in interests[:3]]

        # ── 6. Detectar patrones (repetido >= 2 y al menos uno con score >= 7) ──
        normalized_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in eligible:
            memory = item.get("memory", {})
            raw = memory.get("value", "")
            normalized = cls._normalize(raw)
            if normalized:
                normalized_groups.setdefault(normalized, []).append(item)

        patterns = []
        seen_norm = set()
        for normalized, items in normalized_groups.items():
            if normalized in seen_norm:
                continue
            count = len(items)
            if count >= 2:
                max_score = max(item.get("score", 0) for item in items)
                if max_score >= 7:
                    seen_norm.add(normalized)
                    raw_value = items[0].get("memory", {}).get("value", "")
                    patterns.append(raw_value)

        identity["patterns"] = patterns

        return identity
