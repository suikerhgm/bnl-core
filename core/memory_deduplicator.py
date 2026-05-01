class MemoryDeduplicator:

    @classmethod
    def deduplicate(cls, ranked_memories: list) -> list:
        seen = set()
        result = []

        for item in ranked_memories:
            memory = item.get("memory", {})
            value = memory.get("value", "").lower().strip()
            value = value.replace(".", "").replace(",", "")
            value = value.replace("-", " ")
            value = " ".join(value.split())


            if value and value in seen:
                continue

            if value:
                seen.add(value)

            result.append(item)

        return result
