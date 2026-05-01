"""
Módulo enrutador de memoria para Nexus BNL.

Responsabilidades:
  1. Analizar el mensaje del usuario
  2. Detectar si es una consulta relacionada con memoria
  3. Retornar decisión (True/False)

NO debe:
  - Llamar al AI
  - Llamar a Notion
  - Acceder a sistemas externos
  - Contener lógica de negocio fuera de la decisión
"""

import logging
import unicodedata
import re

logger = logging.getLogger(__name__)


class MemoryRouter:
    """
    Enrutador de memoria basado en reglas (V1).

    Decide si un mensaje del usuario debe responderse desde memoria
    en lugar de llamar al AI o a herramientas externas.
    """

    MEMORY_QUERIES = {
        "como se llama",
        "que nombre",
        "que dije",
        "recuerdas",
        "te dije",
        "what did i say",
        "what is my",
        "do you remember",
    }

    PERSONAL_CONTEXT_QUERIES = {
        "mi proyecto",
        "mi sistema",
        "mi empresa",
        "my project",
        "my system",
    }

    @staticmethod
    def _normalize(text: str) -> str:
        """Normaliza texto: lowercase, sin acentos, sin puntuación."""
        text = text.lower().strip()
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = re.sub(r"[^\w\s]", "", text)
        return text

    def should_use_memory(self, user_message: str) -> bool:
        """
        Decide si un mensaje debe responderse desde memoria.

        Args:
            user_message: Mensaje del usuario.

        Returns:
            True si el mensaje es una consulta de memoria,
            False en caso contrario.
        """
        text = self._normalize(user_message)

        # ── Memory queries ─────────────────────────────────────
        for pattern in self.MEMORY_QUERIES:
            if pattern in text:
                logger.debug("Memory query detectada: «%s»", pattern)
                return True

        # ── Personal context queries ───────────────────────────
        for pattern in self.PERSONAL_CONTEXT_QUERIES:
            if pattern in text:
                logger.debug("Personal context query detectada: «%s»", pattern)
                return True

        return False
