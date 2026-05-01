from typing import Dict, List

from app.services.telegram_service import call_ai_with_fallback


class NotionCleanerAgent:

    def __init__(self):
        pass

    async def analyze_pages(self, pages: List[Dict]) -> Dict:

        content = "\n".join([
            str(p.get("properties", {}))
            for p in pages[:5]
        ])

        messages = [
            {
                "role": "system",
                "content": "Eres un arquitecto de conocimiento. Analiza información desordenada y organízala."
            },
            {
                "role": "user",
                "content": f"""
Analiza estas páginas de Notion:

{content}

Responde en JSON con:
- summary
- entities
- structure
- duplicates
"""
            }
        ]

        response, _ = await call_ai_with_fallback(messages)

        return {
            "analysis": response["content"]
        }

    async def build_clean_page(self, content: Dict) -> Dict:
        """
        Converts messy data into structured content
        """
        return {
            "title": "Nueva estructura limpia",
            "content": str(content)
        }
