class MemoryInference:

    @classmethod
    def infer(cls, ranked_memories: list) -> list:
        inferred_text = "estás desarrollando un sistema de inteligencia artificial"

        if any(
            item.get("memory", {}).get("key") == "inference" and
            item.get("memory", {}).get("value") == inferred_text
            for item in ranked_memories
        ):
            return ranked_memories

        goal = None

        for item in ranked_memories:
            memory = item.get("memory", {})
            key = memory.get("key")

            if key == "goal" and not goal:
                goal = memory.get("value", "")

        if not goal:
            return ranked_memories

        goal_lower = (goal or "").lower()

        keywords = ["agentes", "ia", "ai", "inteligencia"]

        if not any(kw in goal_lower for kw in keywords):
            return ranked_memories

        inferred = {
            "memory": {
                "key": "inference",
                "value": inferred_text
            },
            "score": 8
        }

        return list(ranked_memories) + [inferred]
