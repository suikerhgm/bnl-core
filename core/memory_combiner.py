from typing import Dict, List

from core.memory_response_layer import MemoryResponseLayer


class MemoryCombiner:

    @classmethod
    def combine(cls, ranked_memories: List[Dict]) -> str:
        valid = [item for item in ranked_memories if item.get("score", 0) >= 8]

        if not valid:
            return ""

        selected = valid[:3]

        sentences = [
            MemoryResponseLayer.generate(item["memory"])
            for item in selected
        ]

        sentences = [s for s in sentences if s]

        if not sentences:
            return ""

        return cls._merge_sentences(sentences)

    @classmethod
    def _merge_sentences(cls, sentences: List[str]) -> str:
        if len(sentences) == 1:
            return sentences[0]

        if len(sentences) == 2:
            return f"{sentences[0]} y {cls._lower(sentences[1])}"

        if len(sentences) == 3:
            return f"{sentences[0]}, {cls._lower(sentences[1])} y {cls._lower(sentences[2])}"

        return ", ".join(sentences[:-1]) + " y " + sentences[-1]

    @staticmethod
    def _lower(text: str) -> str:
        if not text:
            return text
        return text[0].lower() + text[1:]
