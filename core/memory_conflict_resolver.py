class MemoryConflictResolver:

    @classmethod
    def resolve(cls, ranked_memories: list) -> list:
        best_per_key = {}

        for idx, item in enumerate(ranked_memories):
            memory = item.get("memory", {})
            key = memory.get("key")

            if not key:
                # memories without key do not participate in conflict resolution
                continue


            score = item.get("score", 0)

            if key not in best_per_key or score > best_per_key[key]["score"]:
                best_per_key[key] = {"item": item, "score": score, "idx": idx}

        seen = set()
        result = []

        for item in ranked_memories:
            memory = item.get("memory", {})
            key = memory.get("key")

            if not key:
                result.append(item)
                continue

            if key in seen:
                continue

            best = best_per_key.get(key)
            if best and best["item"] is item:
                seen.add(key)
                result.append(item)

        return result
