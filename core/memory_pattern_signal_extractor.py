"""
MemoryPatternSignalExtractor

Extrae señales de patrón (pattern_signals) desde mensajes de usuario
para alimentar a MemoryPatternIntegrator.

Fully deterministic — sin AI, sin aleatoriedad, sin efectos secundarios.
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class MemoryPatternSignalExtractor:
    """
    Extrae pattern_signals del mensaje del usuario basado en
    detección determinista de palabras clave por dimensión (tone, depth, style).

    Retorna una lista de señales, cada una con:
        - "type": str (dimensión: "tone", "depth", "style")
        - "value": str (valor detectado, ej: "formal", "deep")
        - "intent": str (intención activa)
        - "weight": float (1.0 por defecto)

    Retorna lista vacía si no se detecta nada.
    """

    # ── Keyword maps por dimensión ──────────────────────────────────

    TONE_KEYWORDS: List[Tuple[List[str], str]] = [
        (["más técnico", "tecnico", "technical"], "technical"),
        (["más casual", "casual"], "casual"),
        (["más directo", "directo"], "direct"),
        (["más formal", "formal"], "formal"),
    ]

    DEPTH_KEYWORDS: List[Tuple[List[str], str]] = [
        (["más detalle", "explica mejor", "más profundo"], "deep"),
        (["resumen", "corto"], "short"),
    ]

    STYLE_KEYWORDS: List[Tuple[List[str], str]] = [
        (["estructura", "ordenado"], "structured"),
        (["historia", "explicación narrativa"], "narrative"),
    ]

    @staticmethod
    def extract(input_data: dict) -> dict:
        """
        Extrae pattern_signals del mensaje del usuario.

        Args:
            input_data: Dict con claves:
                - "message" (str): Mensaje del usuario.
                - "intent" (str): Intención activa.
                - "behavior" (dict): Comportamiento actual (reservado para futuro).

        Returns:
            Dict con clave "pattern_signals" conteniendo una lista de señales.

        Ejemplo:
            >>> extractor = MemoryPatternSignalExtractor()
            >>> result = extractor.extract({
            ...     "message": "Quiero algo más formal y técnico",
            ...     "intent": "request",
            ...     "behavior": {}
            ... })
            >>> result["pattern_signals"]
            [{'type': 'tone', 'value': 'formal', 'intent': 'request', 'weight': 1.0},
             {'type': 'tone', 'value': 'technical', 'intent': 'request', 'weight': 1.0}]
        """
        # ── Safe guard: input validation ───────────────────────────
        if not isinstance(input_data, dict):
            logger.warning("MemoryPatternSignalExtractor: input_data is not a dict")
            return {"pattern_signals": []}

        message = input_data.get("message")
        intent = input_data.get("intent")

        if not isinstance(message, str) or not message.strip():
            logger.debug("MemoryPatternSignalExtractor: empty or invalid message")
            return {"pattern_signals": []}

        if not isinstance(intent, str):
            intent = ""

        # ── Normalize ──────────────────────────────────────────────
        normalized: str = message.lower().strip()

        # ── Extract signals ────────────────────────────────────────
        signals: List[Dict[str, Any]] = []

        # Tone signals
        signals.extend(
            MemoryPatternSignalExtractor._detect_dimension(
                normalized, intent, "tone", MemoryPatternSignalExtractor.TONE_KEYWORDS
            )
        )

        # Depth signals
        signals.extend(
            MemoryPatternSignalExtractor._detect_dimension(
                normalized, intent, "depth", MemoryPatternSignalExtractor.DEPTH_KEYWORDS
            )
        )

        # Style signals
        signals.extend(
            MemoryPatternSignalExtractor._detect_dimension(
                normalized, intent, "style", MemoryPatternSignalExtractor.STYLE_KEYWORDS
            )
        )

        logger.debug(
            "MemoryPatternSignalExtractor: extracted %d signals from message '%s'",
            len(signals),
            message[:50],
        )

        return {"pattern_signals": signals}

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _detect_dimension(
        normalized_message: str,
        intent: str,
        dimension: str,
        keyword_map: List[Tuple[List[str], str]],
    ) -> List[Dict[str, Any]]:
        """
        Detecta señales para una dimensión específica usando su mapa de palabras clave.

        Args:
            normalized_message: Mensaje normalizado (lowercase, stripped).
            intent: Intención activa.
            dimension: Nombre de la dimensión ("tone", "depth", "style").
            keyword_map: Lista de tuplas (lista_de_palabras_clave, valor).

        Returns:
            Lista de señales detectadas para esta dimensión.
        """
        signals: List[Dict[str, Any]] = []

        for keywords, value in keyword_map:
            for kw in keywords:
                if kw in normalized_message:
                    signals.append({
                        "type": dimension,
                        "value": value,
                        "intent": intent,
                        "weight": 1.0,
                    })
                    # Una vez detectado este valor, pasar al siguiente par
                    break

        return signals
