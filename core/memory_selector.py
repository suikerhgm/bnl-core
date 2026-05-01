"""
Selector determinista de memoria.
Elige la memoria más relevante según la consulta del usuario.
Smart Scoring v2: detección de intención + match por contenido + desempate por recencia.
"""

STOPWORDS = {
    "mi", "el", "la", "de", "es", "un", "una",
    "proyecto", "nombre", "objetivo"
}


class MemorySelector:
    """Selecciona la mejor memoria de una lista según la query del usuario."""

    def select(self, memories: list, query: str) -> dict:
        if not memories:
            return None

        query_lower = query.lower()

        scored = []

        for idx, mem in enumerate(memories):
            score = self._score(mem, query_lower)

            # desempate por recencia (más reciente gana)
            recency_bonus = idx / max(len(memories), 1)

            scored.append((score + recency_bonus, mem))

        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_memory = scored[0]

        return best_memory

    def rank(self, memories: list, query: str) -> list:
        if not memories:
            return []

        query_lower = query.lower()
        result = []

        for idx, mem in enumerate(memories):
            score = self._score(mem, query_lower)
            recency_bonus = idx / max(len(memories), 1)
            result.append((score + recency_bonus, {"memory": mem, "score": score}))

        result.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in result]


    def _score(self, memory: dict, query_lower: str) -> int:

        key = memory.get("key", "")
        value = (memory.get("value") or "").lower()
        tags = memory.get("tags", [])

        score = 0

        # ─────────────────────────────
        # 1. DETECCIÓN DE INTENCIÓN (más robusta)
        # ─────────────────────────────

        # USER NAME
        if any(q in query_lower for q in [
            "nombre", "me llamo", "como me llamo", "cómo me llamo",
            "quien soy", "quién soy", "mi identidad"
        ]):
            if key == "user_name":
                score += 12

        # PROJECT
        if any(q in query_lower for q in [
            "proyecto", "project", "startup", "mi app"
        ]):
            if key == "project_name":
                score += 12

        # GOAL
        if any(q in query_lower for q in [
            "objetivo", "meta", "goal", "para que", "para qué"
        ]):
            if key == "goal":
                score += 12

        # GENERIC MEMORY QUESTIONS
        if any(q in query_lower for q in [
            "que sabes", "qué sabes", "que recuerdas", "qué recuerdas",
            "que te dije", "qué te dije"
        ]):
            if key != "general":
                score += 2  # leve, deja competir

        # ─────────────────────────────
        # 2. MATCH POR PALABRAS (controlado)
        # ─────────────────────────────

        if value:
            matched = 0
            for word in value.split():
                if word in STOPWORDS:
                    continue
                if len(word) > 2 and f" {word} " in f" {query_lower} ":
                    score += 2
                    matched += 1
                    if matched >= 2:
                        break

        # ─────────────────────────────
        # 3. EXACT MATCH BONUS
        # ─────────────────────────────

        if value and value in query_lower:
            score += 2

        # ─────────────────────────────
        # 4. MATCH POR TAGS
        # ─────────────────────────────

        for tag in tags:
            if tag in query_lower:
                score += 2

        # ─────────────────────────────
        # 5. FALLBACK BASE
        # ─────────────────────────────

        if key:
            score += 1

        # ─────────────────────────────
        # 6. IMPORTANCE BONUS (normalizado)
        # ─────────────────────────────

        importance = memory.get("importance", 1)
        score += min(importance, 3)

        # ─────────────────────────────
        # 7. PENALIZACIONES
        # ─────────────────────────────

        if key == "general":
            score -= 1

        if "nombre" in query_lower and key != "user_name":
            score -= 2

        if "proyecto" in query_lower and key != "project_name":
            score -= 2

        # ─────────────────────────────
        # 8. CLAMP FINAL
        # ─────────────────────────────

        score = max(score, 0)

        return score
