"""
Capa de comportamiento adaptativo de memoria para Nexus BNL.
Determina CÓMO debe responder el sistema (tono, profundidad, estilo, verbosidad).
Determinista — sin AI, sin persistencia, sin mutación.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MemoryAdaptiveBehaviorLayer:
    """
    Capa que decide el estilo de respuesta basado en memorias seleccionadas,
    identidad del usuario, consulta e intención.

    Se inserta entre MemoryDecisionLayer y MemorySynthesizer.
    No modifica los datos de entrada — retorna un dict de comportamiento nuevo.

    Output:
        {
            "tone": "casual | technical | direct",
            "depth": "short | medium | deep",
            "style": "structured | narrative | concise",
            "verbosity": int  # 1–5
        }
    """

    def apply(
        self,
        selected_memories: List[Dict[str, Any]],
        identity: Dict[str, Any],
        query: str,
        intent: str,
    ) -> Dict[str, Any]:
        """
        Determina el comportamiento de respuesta basado en entradas deterministas.

        Args:
            selected_memories: Output de MemoryDecisionLayer (top N memorias).
            identity: Dict con perfil de identidad del usuario.
            query: Mensaje original del usuario.
            intent: Intención ya computada ("general", "action", "profile").

        Returns:
            Dict con claves: tone, depth, style, verbosity.
        """
        # ── 1. Resolver perfil base ────────────────────────────────────
        tone: str = self._resolve_tone(intent, query, identity)
        depth: str = self._resolve_depth(intent, selected_memories)
        style: str = self._resolve_style(intent, depth)
        verbosity: int = self._resolve_verbosity(selected_memories)

        # ── 2. Ajustes por identidad ──────────────────────────────────
        tone, depth, style, verbosity = self._apply_identity_adjustments(
            tone, depth, style, verbosity, identity
        )

        behavior: Dict[str, Any] = {
            "tone": tone,
            "depth": depth,
            "style": style,
            "verbosity": verbosity,
        }

        return behavior

    # ── Métodos privados de resolución ───────────────────────────────

    @staticmethod
    def _resolve_tone(intent: str, query: str, identity: Dict[str, Any]) -> str:
        """
        Determina el tono de la respuesta.

        Reglas:
            - intent == "action"        → "direct"
            - query contiene "how"/"como" → "technical"
            - identity tiene "user_name" → "casual"
            - default                   → "direct"
        """
        if intent == "action":
            return "direct"

        query_lower = query.lower().strip()
        if "how" in query_lower or "como" in query_lower:
            return "technical"

        if identity.get("user_name"):
            return "casual"

        return "direct"

    @staticmethod
    def _resolve_depth(intent: str, selected_memories: List[Dict[str, Any]]) -> str:
        """
        Determina la profundidad de la respuesta.

        Reglas:
            - intent == "action"              → "short"
            - len(selected_memories) >= 4     → "deep"
            - default                          → "medium"
        """
        if intent == "action":
            return "short"

        if len(selected_memories) >= 4:
            return "deep"

        return "medium"

    @staticmethod
    def _resolve_style(intent: str, depth: str) -> str:
        """
        Determina el estilo de la respuesta.

        Reglas:
            - intent == "action"   → "concise"
            - depth == "deep"      → "structured"
            - default               → "narrative"
        """
        if intent == "action":
            return "concise"

        if depth == "deep":
            return "structured"

        return "narrative"

    @staticmethod
    def _resolve_verbosity(selected_memories: List[Dict[str, Any]]) -> int:
        """
        Determina el nivel de verbosidad (1–5).

        Regla:
            verbosity = min(5, max(1, len(selected_memories)))
        """
        return min(5, max(1, len(selected_memories)))

    @staticmethod
    def _apply_identity_adjustments(
        tone: str,
        depth: str,
        style: str,
        verbosity: int,
        identity: Dict[str, Any],
    ) -> tuple:
        """
        Aplica ajustes al perfil de comportamiento basados en patrones de identidad.

        Reglas:
            - "technical" en identity["patterns"]:
                tone = "technical", depth = "deep"

            - "fast_decision" en identity["patterns"]:
                style = "concise", verbosity = 2
        """
        patterns = identity.get("patterns", [])

        if "technical" in patterns:
            tone = "technical"
            depth = "deep"

        if "fast_decision" in patterns:
            style = "concise"
            verbosity = 2

        return tone, depth, style, verbosity
