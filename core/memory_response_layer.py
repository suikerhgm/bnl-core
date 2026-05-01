"""
Capa de transformación de memoria estructurada a lenguaje natural.
Responsabilidad: convertir memoria → respuesta natural sin usar AI.
Solo reglas deterministas y templates.
"""
import logging

logger = logging.getLogger(__name__)


class MemoryResponseLayer:
    """
    Convierte memoria estructurada en respuestas en lenguaje natural.

    INPUT esperado:
        {
            "type": "fact",
            "key": "project_name",
            "value": "Nexus BNL",
            "summary": "mi proyecto se llama Nexus BNL"
        }

    OUTPUT:
        "Tu proyecto se llama Nexus BNL"
    """

    # ── Templates para hechos conocidos ─────────────────────────────
    FACT_TEMPLATES = {
        "project_name": "Tu proyecto se llama {value}",
        "user_name": "Te llamas {value}",
        "goal": "Tu objetivo es {value}",
    }

    # ── Palabras clave para detectar tipo de hecho ─────────────────
    KEYWORD_MAP = {
        "project_name": ["proyecto", "project"],
        "user_name": ["llamo", "llamas", "nombre", "name", "usuario", "user", "llama"],
        "goal": ["objetivo", "goal", "meta", "propósito", "proposito"],
    }

    def generate(self, memory: dict) -> str:
        """
        Punto de entrada principal.

        Args:
            memory: Dict de memoria. Puede venir en formato estructurado
                    (type, key, value) o en formato raw (summary, content).

        Returns:
            str: Respuesta en lenguaje natural.
        """
        memory_type = memory.get("type")
        key = memory.get("key")
        value = memory.get("value")

        # ── Si ya viene estructurado, usar templates ────────────
        if memory_type == "fact" and key and value:
            return self._handle_fact(key, value)

        # ── Si no está estructurado, intentar extraer campos ────
        extracted = self._extract_fields(memory)
        if extracted:
            return self._handle_fact(extracted["key"], extracted["value"])

        # ── Fallback: devolver summary limpio ───────────────────
        return self._handle_fallback(memory)

    # ── Método estático público para limpiar valor desde orchestrator ──

    @staticmethod
    def _extract_clean_value(text: str, key_hint: str | None = None) -> str:
        """
        Extrae el valor limpio de un texto como 'Recuerda esto: mi proyecto se llama Nexus BNL'.

        Útil para que el orchestrator limpie el value antes de guardar.

        Args:
            text: Texto raw del usuario.
            key_hint: Sugerencia de key (opcional).

        Returns:
            str: Valor limpio extraído.
        """
        import re

        text_lower = text.lower()

        # Estrategia 1: después de "llama", "llamo", "nombre", etc.
        for trigger in ["llama", "llamo", "llamas", "nombre es", "name is",
                        "objetivo es", "goal is", "meta es",
                        "propósito es", "proposito es"]:
            pattern = re.compile(
                re.escape(trigger) + r"\s+(.+?)$", re.IGNORECASE
            )
            match = pattern.search(text)
            if match:
                return match.group(1).strip().rstrip(".,!?")

        # Estrategia 2: después de ":" o " es "
        for sep in [":", " es ", " is "]:
            if sep in text_lower:
                parts = text.split(sep, 1)
                if len(parts) > 1:
                    candidate = parts[1].strip().rstrip(".,!?")
                    if candidate:
                        return candidate

        # Estrategia 3: limpiar prefijos y devolver resto
        cleaned = re.sub(
            r"^(recuerda esto:|remember:)\s*", "", text, flags=re.IGNORECASE
        ).strip()
        if cleaned:
            return cleaned

        return text

    # ── Métodos privados ──────────────────────────────────────────

    def _handle_fact(self, key: str, value: str) -> str:
        """
        Aplica el template correspondiente al key.

        Si el key no está registrado, devuelve el valor capitalizado.
        """
        template = self.FACT_TEMPLATES.get(key)
        if template:
            return template.format(value=value)

        # Fallback: solo devolver el valor con primera mayúscula
        return value[0].upper() + value[1:] if value else ""

    def _extract_fields(self, memory: dict) -> dict | None:
        """
        Intenta extraer type/key/value de un memory dict en formato raw.

        Busca en: summary → content → value

        Returns:
            dict con {"key": str, "value": str} o None si no puede extraer.
        """
        # Fuentes de texto para análisis
        text = (
            memory.get("summary", "")
            or memory.get("content", "")
            or memory.get("value", "")
        )
        if not text:
            return None

        # Determinar key por palabras clave
        key = self._detect_key(text.lower())
        if not key:
            return None

        # Extraer el valor (última parte significativa del texto)
        value = self._extract_value(text, key)

        if value:
            return {"key": key, "value": value}

        return None

    def _detect_key(self, text_lower: str) -> str | None:
        """
        Detecta el tipo de hecho basado en palabras clave en el texto.
        """
        for key, keywords in self.KEYWORD_MAP.items():
            for kw in keywords:
                if kw in text_lower:
                    return key
        return None

    def _extract_value(self, text: str, key: str) -> str:
        """
        Extrae el valor significativo del texto para el key detectado.

        Estrategias:
          1. Buscar después de palabras clave como "llama", "llamo", "nombre"
          2. Buscar después de ":" o "es"
          3. Limpiar prefijos como "recuerda esto:", "remember:"
        """
        import re

        text_lower = text.lower()

        # ── Estrategia 1: después de "llama", "llamo", "nombre", etc. ──
        for trigger in ["llama", "llamo", "llamas", "nombre es", "name is",
                        "objetivo es", "goal is", "meta es",
                        "propósito es", "proposito es"]:
            pattern = re.compile(
                re.escape(trigger) + r"\s+(.+?)$", re.IGNORECASE
            )
            match = pattern.search(text)
            if match:
                return match.group(1).strip().rstrip(".,!?")

        # ── Estrategia 2: después de ":" o "es " ──
        for sep in [":", " es ", " is "]:
            if sep in text_lower:
                parts = text.split(sep, 1)
                if len(parts) > 1:
                    candidate = parts[1].strip().rstrip(".,!?")
                    if candidate:
                        return candidate

        # ── Estrategia 3: limpiar prefijos y devolver resto ──
        cleaned = re.sub(
            r"^(recuerda esto:|remember:)\s*", "", text, flags=re.IGNORECASE
        ).strip()
        if cleaned:
            return cleaned

        return text

    def _handle_fallback(self, memory: dict) -> str:
        """
        Fallback final: devuelve el summary limpio y capitalizado.
        """
        summary = memory.get("summary", "")

        if not summary:
            return ""

        import re

        # Limpiar prefijos de comando
        cleaned = re.sub(
            r"^(recuerda esto:|remember:)\s*", "", summary, flags=re.IGNORECASE
        ).strip()

        # Capitalizar primera letra
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]

        return cleaned
