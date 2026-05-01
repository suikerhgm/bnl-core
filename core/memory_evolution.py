class MemoryEvolution:

    @classmethod
    def evolve(cls, ranked_memories: list) -> list:
        seen_keys = set()
        result = []

        for item in ranked_memories:
            memory = dict(item.get("memory", {}))
            key = memory.get("key")
            score = item.get("score", 0)

            if key is None:
                result.append({"memory": memory, "score": score})
                continue


            if key not in seen_keys:
                memory["status"] = "active"
                seen_keys.add(key)
            else:
                memory["status"] = "deprecated"

            result.append({"memory": memory, "score": score})

        return result


