"""
Integrador de patrones de memoria para Nexus BNL.
Acumula pesos de señales de patrón en la identidad del usuario.
Determinista — sin AI, sin normalización, sin decaimiento.
"""
import logging
import math
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MemoryPatternIntegrator:
    """
    Integrador que acumula señales de patrón en identity["patterns"].

    Reglas:
        - Solo modifica identity["patterns"].
        - No remueve ni sobrescribe valores existentes.
        - Solo acumula pesos (setdefault + +=).
        - No normaliza, decae ni poda.
        - Determinista: misma entrada → misma salida.
        - Idempotente por ejecución.
        - Robusto ante entradas malformadas.
    """

    @staticmethod
    def integrate(input_data: dict) -> dict:
        """
        Acumula señales de patrón en la identidad.

        Args:
            input_data: Dict con las claves:
                - "pattern_signals" (list): Lista de señales, cada una con
                    "type" (str), "value" (str), "intent" (str), "weight" (float).
                - "identity" (dict): Identidad actual del usuario.

        Returns:
            Dict con "identity" actualizado.

        Ejemplo de uso:
            >>> integrator = MemoryPatternIntegrator()
            >>> result = integrator.integrate({
            ...     "pattern_signals": [
            ...         {"type": "tone", "value": "formal", "intent": "greeting", "weight": 1.5}
            ...     ],
            ...     "identity": {}
            ... })
            >>> result["identity"]["patterns"]["tone"]["greeting"]["formal"]
            1.5
        """
        signals: List[Any] = input_data.get("pattern_signals", [])
        identity: Dict[str, Any] = input_data.get("identity", {})

        if not isinstance(signals, list):
            signals = []

        if not isinstance(identity, dict):
            identity = {}

        # ── 1. Safe initialization ───────────────────────────────
        # Avoid shared references and protect against malformed inputs
        if "patterns" not in identity or not isinstance(identity["patterns"], dict):
            identity["patterns"] = {}

        for category in ("tone", "depth", "style"):
            if category not in identity["patterns"] or not isinstance(
                identity["patterns"][category], dict
            ):
                identity["patterns"][category] = {}

        # ── 2. Procesar cada señal ───────────────────────────────
        for signal in signals:
            # ── FIX 3: Signal sanitization ────────────────────────
            if not isinstance(signal, dict):
                continue

            sig_type = signal.get("type")
            intent = signal.get("intent")
            value = signal.get("value")

            if not all(isinstance(x, str) and x.strip() for x in (sig_type, intent, value)):
                continue

            sig_type = sig_type.strip()
            intent = intent.strip()
            value = value.strip()

            weight = signal.get("weight")

            # ── FIX 2: Strict weight validation ────────────────────
            if not isinstance(weight, (int, float)):
                continue

            if weight <= 0:
                continue

            if isinstance(weight, float) and (math.isnan(weight) or math.isinf(weight)):
                continue

            # ── FIX 4: Type-safe structure ─────────────────────────
            identity["patterns"].setdefault(sig_type, {})
            if not isinstance(identity["patterns"][sig_type], dict):
                identity["patterns"][sig_type] = {}

            identity["patterns"][sig_type].setdefault(intent, {})
            if not isinstance(identity["patterns"][sig_type][intent], dict):
                identity["patterns"][sig_type][intent] = {}

            # ── FIX 5: Controlled accumulation ─────────────────────
            identity["patterns"][sig_type][intent].setdefault(value, 0.0)
            identity["patterns"][sig_type][intent][value] += float(weight)

        # ── FIX 7: Safe logging guard ─────────────────────────────
        logger.debug("Integrated %d signals into identity patterns", len(signals))

        # ── OUTPUT ───────────────────────────────────────────────
        return {"identity": identity}
