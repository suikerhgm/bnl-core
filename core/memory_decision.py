"""
Capa de decisión de memoria para Nexus BNL.
Determina qué memorias priorizar, ignorar y cómo dar forma al contexto de respuesta.
Determinista — sin AI, sin persistencia, sin mutación.
"""
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MemoryDecisionLayer:
    """
    Capa que decide qué memorias usar para la respuesta.

    Se inserta entre MemoryIdentityLayer y MemorySynthesizer.
    No modifica los datos de entrada — retorna una nueva lista filtrada y re-scoreada.

    Lógica:
        1. Normalizar mensaje del usuario + detección ligera de intención
        2. Re-scorear cada memoria según relevancia contextual (word-based + stemming)
        3. Penalizar ruido solo en memorias generales débiles
        4. Ordenar por nuevo score descendente
        5. Selección diversa: priorizar identidad por relevancia + top scores, evitar duplicados
        6. Retornar copia filtrada
    """

    # Keys fuertemente ligadas a identidad, en orden de prioridad
    IDENTITY_KEYS: List[str] = ["user_name", "project_name", "goal"]
    IDENTITY_PRIORITY: List[str] = ["goal", "project_name", "user_name"]

    @staticmethod
    def _normalize(text: str) -> str:
        """Normaliza texto para comparación determinista."""
        return text.lower().strip()

    @staticmethod
    def _stem(word: str) -> str:
        """
        Stemming ligero: elimina 's' final en palabras de más de 3 caracteres.
        Permite que "agentes" coincida con "agente", "python" sigue siendo "python".
        """
        if word.endswith("s") and len(word) > 3:
            return word[:-1]
        return word

    @classmethod
    def _word_based_match(cls, value: str, message: str) -> bool:
        """
        Verifica si hay al menos una palabra en común entre value y message,
        aplicando stemming básico para robustez lingüística.
        Previene falsos positivos como "ia" dentro de "familia".
        """
        message_words: Set[str] = {cls._stem(w) for w in message.split()}
        value_words: Set[str] = {cls._stem(w) for w in cls._normalize(value).split()}
        return bool(message_words & value_words)

    @classmethod
    def _detect_intent(cls, message: str) -> str:
        """
        Detecta intención ligera del mensaje del usuario.
        Returns: "general", "action", o "profile"
        """
        if "como" in message or "cómo" in message or "how" in message:
            return "action"
        if "que sabes" in message or "qué sabes" in message or "perfil" in message or "sobre mi" in message or "sobre mí" in message:
            return "profile"
        return "general"

    def detect_intent(self, query: str) -> str:
        """
        Método público para detectar intención.
        Delega al método privado _detect_intent.
        """
        return self._detect_intent(query)

    @classmethod
    def _select_diverse(
        cls,
        scored: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Selección diversa con prioridad de identidad.

        Estrategia:
            1. Priorizar por tipo: goal > project_name > user_name
            2. Si existe, incluir la mejor de cada tipo (la de mayor score por tipo)
            3. Llenar hasta 5 slots con las memorias de mayor score
            4. Evitar duplicados de mismo (key, value)
        """
        # Agrupar candidatos de identidad por tipo
        identity_by_type: Dict[str, List[Dict[str, Any]]] = {}
        other_candidates: List[Dict[str, Any]] = []

        for item in scored:
            key = item.get("memory", {}).get("key", "")
            if key in cls.IDENTITY_KEYS:
                identity_by_type.setdefault(key, []).append(item)
            else:
                other_candidates.append(item)

        seen_pairs: Set[Tuple[str, str]] = set()
        selected: List[Dict[str, Any]] = []

        # Step 1: seleccionar en orden de prioridad goal > project_name > user_name
        for priority_key in cls.IDENTITY_PRIORITY:
            if len(selected) >= 5:
                break
            candidates = identity_by_type.get(priority_key, [])
            if candidates:
                # candidates ya ordenados por score descendente
                best = candidates[0]
                pair = (best["memory"]["key"], best["memory"]["value"])
                if pair not in seen_pairs:
                    selected.append(best)
                    seen_pairs.add(pair)

        # Step 2: llenar con identidades restantes + otras memorias
        all_remaining: List[Dict[str, Any]] = []
        for key in cls.IDENTITY_PRIORITY:
            candidates = identity_by_type.get(key, [])
            all_remaining.extend(candidates[1:] if candidates else [])
        all_remaining.extend(other_candidates)

        for item in all_remaining:
            if len(selected) >= 5:
                break
            pair = (item["memory"]["key"], item["memory"]["value"])
            if pair not in seen_pairs:
                selected.append(item)
                seen_pairs.add(pair)

        return selected

    @classmethod
    def decide(
        cls,
        ranked_memories: List[Dict[str, Any]],
        identity: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filtra y re-score memorias basándose en el mensaje del usuario y su identidad.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score".
            identity: Dict con perfil de identidad del usuario.
            user_message: Mensaje original del usuario.
            intent: Intención precomputada. Si es None, se detecta internamente.

        Returns:
            Lista nueva con las top 5 memorias re-scoreadas (sin mutar original).
        """
        if not ranked_memories:
            return []

        # ── 1. Normalizar mensaje del usuario + detectar intención ────
        normalized_message: str = cls._normalize(user_message)

        intent = intent or cls._detect_intent(normalized_message)

        # ── 2-3. Re-scorear y filtrar ────────────────────────────────────
        result: List[Dict[str, Any]] = []

        for item in ranked_memories:
            memory = item.get("memory", {})
            base_score = item.get("score", 0)

            # Ignorar memorias deprecated
            if memory.get("status") == "deprecated":
                continue

            value = memory.get("value", "")
            key = memory.get("key", "")

            if not value:
                continue

            score = base_score

            # +3 si al menos una palabra del valor coincide con el mensaje
            if value and cls._word_based_match(value, normalized_message):
                score += 3

            # +2 si la key está fuertemente ligada a identidad
            if key in cls.IDENTITY_KEYS:
                score += 2

            # +2 si el valor está en identity["patterns"]
            if value in identity.get("patterns", []):
                score += 2

            # +1 si el valor está en identity["interests"]
            if value in identity.get("interests", []):
                score += 1

            # Ajuste por intención detectada
            if intent == "action" and key == "goal":
                score += 2
            if intent == "profile" and key in ["user_name", "project_name"]:
                score += 2

            # Penalizar ruido: solo memorias "general" cuyo score final
            # sea menor al base (es decir, no recibieron bonus significativo)
            if key == "general" and score < base_score:
                score -= 2

            # Construir nuevo item sin mutar el original
            new_item = dict(item)  # shallow copy del dict externo
            new_item["score"] = score
            result.append(new_item)

        # ── 4. Ordenar por score descendente ────────────────────────────
        result.sort(key=lambda x: x.get("score", 0), reverse=True)

        # ── 5. Selección diversa ────────────────────────────────────────
        selected = cls._select_diverse(result)

        return selected
