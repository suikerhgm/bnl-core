"""
Sintetizador de memoria para Nexus BNL.
Convierte memorias seleccionadas + identidad + comportamiento en respuesta final.
Comportamiento-aware: tono, profundidad, estilo y verbosidad controlan el output.
Determinista — sin AI, sin persistencia, sin mutación.
"""
from typing import Dict, List, Optional

from core.memory_response_layer import MemoryResponseLayer


class MemorySynthesizer:

    @classmethod
    def synthesize(
        cls,
        ranked_memories: List[Dict],
        identity: Optional[Dict] = None,
        behavior: Optional[Dict] = None,
    ) -> str:
        """
        Sintetiza una respuesta a partir de memorias, identidad y comportamiento.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score" (output de DecisionLayer).
            identity: Dict con perfil de identidad del usuario.
            behavior: Dict con tone, depth, style, verbosity (output de AdaptiveBehaviorLayer).

        Returns:
            String con la respuesta formateada según el comportamiento.
        """
        # ── Safety fallback: sin behavior, usar lógica original ──────
        if behavior is None:
            return cls._synthesize_legacy(ranked_memories, identity)

        valid = [item for item in ranked_memories if item.get("score", 0) >= 8]

        if not valid:
            return ""

        selected = valid[:5]

        identity_mem = None
        project = None
        goal = None
        inference = None
        others = []

        # ── Identity-driven: construir desde identidad primero ─────
        if identity:
            if identity.get("user_name"):
                identity_mem = {"key": "user_name", "value": identity["user_name"]}
            if identity.get("project_name"):
                project = {"key": "project_name", "value": identity["project_name"]}
            if identity.get("goals"):
                raw_goals = identity["goals"]
                if raw_goals:
                    for g in raw_goals:
                        goal = {"key": "goal", "value": g}
                        break
            if identity.get("interests"):
                for interest in identity["interests"]:
                    others.append({"key": "general", "value": interest})
            if identity.get("patterns"):
                pattern_values = {o.get("value") for o in others}
                for pattern in identity["patterns"]:
                    if pattern not in pattern_values:
                        others.append({"key": "general", "value": pattern})
                        pattern_values.add(pattern)

        # ── Fallback: completar campos faltantes desde el pipeline ─
        for item in selected:
            mem = item.get("memory", {})

            key = mem.get("key")

            if key == "user_name" and not identity_mem:
                identity_mem = mem
            elif key == "project_name" and not project:
                project = mem
            elif key == "goal" and not goal:
                goal = mem
            elif key == "inference" and not inference:
                inference = mem
            elif key and key != "general":
                existing_values = {o.get("value") for o in others}
                if mem.get("value") not in existing_values:
                    others.append(mem)

        # ── Construir raw_parts tipados (fuente única) ─────────────
        raw_parts: List[Dict[str, str]] = []

        if identity_mem:
            raw_parts.append({
                "type": "identity",
                "text": MemoryResponseLayer.generate(identity_mem),
            })

        if project:
            value = project.get("value")
            if value:
                raw_parts.append({
                    "type": "project",
                    "text": f"estás trabajando en {value}",
                })

        if goal:
            raw_parts.append({
                "type": "goal",
                "text": MemoryResponseLayer.generate(goal),
            })

        # ── 1. Verbosity control ──────────────────────────────────────
        verbosity_limit = behavior.get("verbosity", 2) if behavior else 2

        for mem in others[:verbosity_limit]:
            raw_parts.append({
                "type": "general",
                "text": MemoryResponseLayer.generate(mem),
            })

        if inference:
            inferred_text = inference.get("value")
            if inferred_text:
                raw_parts.append({
                    "type": "inference",
                    "text": f"por lo que {inferred_text}",
                })

        raw_parts = [p for p in raw_parts if p.get("text") and p["text"].strip()]

        if not raw_parts:
            return ""

        # ── 2. Depth control ──────────────────────────────────────────
        filtered_parts = cls._apply_depth(raw_parts, behavior)

        # ── 3. Tone adjustments on individual parts ───────────────────
        filtered_parts = cls._apply_tone_to_parts(filtered_parts, behavior)

        # ── 4. Style projection ───────────────────────────────────────
        return cls._apply_style(filtered_parts, behavior)

    # ── Helpers ─────────────────────────────────────────────────────

    @classmethod
    def _apply_depth(
        cls,
        parts: List[Dict[str, str]],
        behavior: Dict,
    ) -> List[Dict[str, str]]:
        """
        Controla la profundidad: limita a 2 partes si depth == "short".
        Preserva la estructura tipada.
        """
        depth = behavior.get("depth", "medium")

        if depth == "short":
            return parts[:2]

        return parts

    @classmethod
    def _apply_tone_to_parts(
        cls,
        parts: List[Dict[str, str]],
        behavior: Dict,
    ) -> List[Dict[str, str]]:
        """
        Aplica ajustes de tono a las partes individuales.
        Opera sobre part["text"] y retorna dicts actualizados.
        Se ejecuta ANTES del merge de estilo.
        """
        tone = behavior.get("tone", "direct")

        if tone == "direct":
            modified = []
            for part in parts:
                stripped = part["text"].strip()
                normalized = stripped.lower().strip()
                # Quitar prefijo "por lo que" si existe
                prefix = "por lo que"
                if normalized.startswith(prefix):
                    rest = stripped[len(prefix):].strip()
                    rest = cls._lower(rest)
                    modified.append({"type": part["type"], "text": rest})
                else:
                    modified.append(part)
            return modified

        return parts

    @classmethod
    def _apply_style(
        cls,
        parts: List[Dict[str, str]],
        behavior: Dict,
    ) -> str:
        """
        Proyecta el listado de partes según el estilo.
        Concise usa types identity/project/goal.
        Structured usa bullet points. Narrative fusiona oraciones.
        Retorna el string final de respuesta.
        """
        style = behavior.get("style", "narrative")

        if style == "concise":
            # Filtrar por tipo: solo identity, project, goal
            concise = [p["text"] for p in parts
                       if p["type"] in ("identity", "project", "goal")]
            if not concise:
                concise = [p["text"] for p in parts[:2]]
            text = cls._build_concise(concise)
            text = cls._apply_tone_prefix(text, behavior)
            return text

        if style == "structured":
            text = "\n".join(f"- {p['text']}" for p in parts)
            text = cls._apply_tone_prefix(text, behavior)
            return text

        # ── Narrative (default) ───────────────────────────────────────
        text = cls._merge_sentences([p["text"] for p in parts])
        text = cls._apply_tone_prefix(text, behavior)
        return text

    @classmethod
    def _build_concise(cls, parts: List[str]) -> str:
        """
        Para estilo conciso: reunir partes mínimas en una línea.
        Si hay pocas partes, se unen con comas.
        """
        if len(parts) <= 2:
            return " y ".join(parts)
        # Más de 2: usar merge normal pero sin inferencia
        return cls._merge_sentences(parts)

    @classmethod
    def _apply_tone_prefix(cls, text: str, behavior: Dict) -> str:
        """
        Agrega prefijo de tono al texto final.
        """
        tone = behavior.get("tone", "direct")

        if tone == "technical":
            return f"Contexto:\n{text}"

        if tone == "casual":
            return f"Oye, {text}"

        return text

    # ── Legado (sin behavior) ────────────────────────────────────────

    @classmethod
    def _synthesize_legacy(
        cls,
        ranked_memories: List[Dict],
        identity: Optional[Dict] = None,
    ) -> str:
        """Lógica original sin comportamiento — usada como fallback."""
        valid = [item for item in ranked_memories if item.get("score", 0) >= 8]

        if not valid:
            return ""

        selected = valid[:5]

        identity_mem = None
        project = None
        goal = None
        inference = None
        others = []

        if identity:
            if identity.get("user_name"):
                identity_mem = {"key": "user_name", "value": identity["user_name"]}
            if identity.get("project_name"):
                project = {"key": "project_name", "value": identity["project_name"]}
            if identity.get("goals"):
                raw_goals = identity["goals"]
                if raw_goals:
                    for g in raw_goals:
                        goal = {"key": "goal", "value": g}
                        break
            if identity.get("interests"):
                for interest in identity["interests"]:
                    others.append({"key": "general", "value": interest})
            if identity.get("patterns"):
                pattern_values = {o.get("value") for o in others}
                for pattern in identity["patterns"]:
                    if pattern not in pattern_values:
                        others.append({"key": "general", "value": pattern})
                        pattern_values.add(pattern)

        for item in selected:
            mem = item.get("memory", {})

            key = mem.get("key")

            if key == "user_name" and not identity_mem:
                identity_mem = mem
            elif key == "project_name" and not project:
                project = mem
            elif key == "goal" and not goal:
                goal = mem
            elif key == "inference" and not inference:
                inference = mem
            elif key and key != "general":
                existing_values = {o.get("value") for o in others}
                if mem.get("value") not in existing_values:
                    others.append(mem)

        parts = []

        if identity_mem:
            parts.append(MemoryResponseLayer.generate(identity_mem))

        if project:
            value = project.get("value")
            if value:
                parts.append(f"estás trabajando en {value}")

        if goal:
            parts.append(MemoryResponseLayer.generate(goal))

        for mem in others[:2]:
            parts.append(MemoryResponseLayer.generate(mem))

        if inference:
            inferred_text = inference.get("value")
            if inferred_text:
                parts.append(f"por lo que {inferred_text}")

        parts = [p for p in parts if p and p.strip()]

        if not parts:
            return ""

        return cls._merge_sentences(parts)

    # ── Merge helpers (narrative) ────────────────────────────────────

    @classmethod
    def _merge_sentences(cls, sentences: List[str]) -> str:
        if len(sentences) == 1:
            return sentences[0]

        if len(sentences) == 2:
            second = cls._lower(sentences[1])
            if second.startswith("por lo que"):
                return f"{sentences[0]} {second}"
            return f"{sentences[0]} y {second}"

        first = sentences[0]
        rest = [cls._lower(s) for s in sentences[1:]]

        if rest[-1].startswith("por lo que"):
            return f"{first}, " + ", ".join(rest[:-1]) + " " + rest[-1]

        return f"{first}, " + ", ".join(rest[:-1]) + " y " + rest[-1]

    @staticmethod
    def _lower(text: str) -> str:
        if not text:
            return text
        return text[0].lower() + text[1:]
