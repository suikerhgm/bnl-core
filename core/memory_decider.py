"""
Módulo decisor de memoria para Nexus BNL.

Responsabilidades:
  1. Analizar mensaje del usuario + respuesta del AI
  2. Decidir si vale la pena almacenar
  3. Generar: summary, tags, importance score
  4. Retornar estructura de memoria estructurada

NO debe:
  - Llamar a Notion directamente
  - Almacenar memoria por sí mismo
  - Contener lógica de orquestación
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryDecider:
    """
    Decisor de memoria basado en reglas (V1).

    Analiza el mensaje del usuario y la respuesta del AI para determinar
    si la interacción debe persistirse como memoria episódica.
    """

    # ── Palabras clave ────────────────────────────────────────────────

    EXPLICIT_MEMORY_KEYWORDS = {
        "recuerda",
        "remember",
        "guarda",
        "guardar",
        "almacena",
        "store",
    }

    HIGH_VALUE_PATTERNS = {
        "mi proyecto",
        "estoy construyendo",
        "mi sistema",
        "my project",
        "i am building",
        "my system",
    }

    # ── API pública ───────────────────────────────────────────────────

    async def decide(
        self,
        user_message: str,
        ai_response: str,
    ) -> Optional[dict]:
        """
        Decide si una interacción debe almacenarse como memoria.

        Args:
            user_message: Mensaje enviado por el usuario.
            ai_response:  Respuesta generada por el AI.

        Returns:
            dict estructurado con la memoria si se debe almacenar,
            None si la interacción no es relevante.
        """
        text = user_message.lower().strip()
        full_text = f"Usuario: {user_message}\nAI: {ai_response}"

        # ── Condition 1: Intención explícita de memoria ──────────
        if self._has_explicit_memory_intent(text):
            summary = self._generate_summary(user_message)
            tags = self._generate_tags(user_message)
            importance = 5
            return self._build_output(full_text, summary, tags, importance)

        # ── Condition 2: Información de alto valor ───────────────
        if self._has_high_value_info(text):
            summary = self._generate_summary(user_message)
            tags = self._generate_tags(user_message)
            importance = 4
            return self._build_output(full_text, summary, tags, importance)

        # ── No se requiere almacenamiento ────────────────────────
        return None

    # ── Métodos internos ──────────────────────────────────────────────

    @classmethod
    def _has_explicit_memory_intent(cls, text: str) -> bool:
        """Detecta si el usuario pide explícitamente guardar memoria."""
        for keyword in cls.EXPLICIT_MEMORY_KEYWORDS:
            if keyword in text:
                logger.debug("Intención explícita de memoria detectada: «%s»", keyword)
                return True
        return False

    @classmethod
    def _has_high_value_info(cls, text: str) -> bool:
        """Detecta si el mensaje contiene información de alto valor."""
        for pattern in cls.HIGH_VALUE_PATTERNS:
            if pattern in text:
                logger.debug("Información de alto valor detectada: «%s»", pattern)
                return True
        return False

    @staticmethod
    def _generate_summary(user_message: str) -> str:
        """
        Genera un resumen corto usando heurística simple.

        Estrategia:
          - Toma la primera oración significativa del mensaje del usuario.
          - Limita a 20 palabras máximo.
          - Sin AI.
        """
        # Dividir en oraciones y tomar la primera no vacía
        sentences = [
            s.strip()
            for s in user_message.replace("?", ".").replace("!", ".").split(".")
            if s.strip()
        ]

        if not sentences:
            return user_message[:80]

        first_sentence = sentences[0]

        # Limitar a 20 palabras
        words = first_sentence.split()
        if len(words) <= 20:
            return first_sentence

        return " ".join(words[:20]) + "..."

    @staticmethod
    def _generate_tags(user_message: str) -> list[str]:
        """
        Asigna etiquetas según el contenido del mensaje.

        Mapeo simple:
          - "proyecto" / "project" → ["project"]
          - "arquitectura" / "architecture" → ["architecture"]
          - Otros → ["context"]
        """
        text = user_message.lower()

        if "proyecto" in text or "project" in text:
            return ["project"]
        if "arquitectura" in text or "architecture" in text:
            return ["architecture"]

        return ["context"]

    @staticmethod
    def _build_output(
        content: str,
        summary: str,
        tags: list[str],
        importance: int,
    ) -> dict:
        """Construye el dict de salida estructurado."""
        return {
            "content": content,
            "summary": summary,
            "tags": tags,
            "importance": importance,
        }
