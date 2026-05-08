# core/agents/specialized/frontend_agent.py
"""
FrontendAgent — generates HTML/CSS/JS frontend for the given description.
For MVP: generates a clean single-page HTML that calls the backend API.
"""
from __future__ import annotations
import time
from pathlib import Path
from ._base import BaseSpecializedAgent, AgentResult

_SYSTEM = """Eres El Forjador, especialista en frontends web modernos.

Genera un frontend HTML/CSS/JS FUNCIONAL para la descripción dada.

FORMATO OBLIGATORIO:
--- FILE: index.html ---
```html
<!DOCTYPE html>
...
</html>
```

REGLAS:
- Un solo archivo HTML con CSS y JS incluidos (sin externos salvo CDN)
- Usa fetch() para llamar al backend en http://localhost:8080
- UI limpia con Tailwind CDN o estilos inline
- Funcional sin dependencias npm para MVP
- Sin TODOs"""


class FrontendAgent(BaseSpecializedAgent):
    agent_type = "frontend"

    async def execute(self, task: dict) -> AgentResult:
        from core.ai_cascade import call_ai_with_fallback
        from core.actions.code_action import _parse_multi_file_response, _CODE_BLOCK_PATTERN
        import re

        task_id = task.get("id", "frontend-task")
        description = task.get("description", "")
        project_path = Path(task.get("project_path", "generated_apps/app"))
        project_path.mkdir(parents=True, exist_ok=True)

        start = int(time.monotonic() * 1000)
        try:
            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Crea el frontend para: {description}"},
            ]
            response = await call_ai_with_fallback(messages)
            if isinstance(response, str) and "\n" not in response and "\\n" in response:
                response = response.replace("\\n", "\n")

            files = _parse_multi_file_response(response) or []
            if not files:
                match = _CODE_BLOCK_PATTERN.search(response)
                if match:
                    files = [{"path": "index.html", "content": match.group(1).strip()}]

            created = []
            for f in files:
                content = _strip_fences(f["content"])
                fpath = project_path / f["path"]
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
                created.append(f["path"])

            return self._result(
                task_id=task_id, success=bool(created),
                output=f"Generated {len(created)} frontend files: {created}",
                files=created,
                duration_ms=int(time.monotonic() * 1000) - start,
            )
        except Exception as e:
            return self._result(task_id=task_id, success=False, output="",
                                error=str(e), duration_ms=int(time.monotonic() * 1000) - start)


def _strip_fences(content: str) -> str:
    import re
    content = re.sub(r"^```[a-zA-Z]*\s*\n?", "", content.strip())
    content = re.sub(r"\n?```\s*$", "", content)
    return content.strip()
