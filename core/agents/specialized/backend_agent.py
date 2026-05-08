# core/agents/specialized/backend_agent.py
"""
BackendAgent — generates Python/FastAPI backend code using the existing AI cascade.
Writes files to the project directory. Uses call_ai_with_fallback directly.
"""
from __future__ import annotations
import time
from pathlib import Path
from ._base import BaseSpecializedAgent, AgentResult

_SYSTEM = """Eres El Forjador, especialista en backends Python con FastAPI.

Genera código backend FUNCIONAL y COMPLETO para la descripción dada.

FORMATO OBLIGATORIO:
--- FILE: main.py ---
```python
# código
```
--- FILE: requirements.txt ---
```
fastapi
uvicorn
```

REGLAS:
- main.py DEBE terminar con: if __name__ == "__main__": import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8080)
- requirements.txt: solo nombres de paquetes, sin bloques ```
- Máximo 3 archivos
- Código completo, sin TODOs
- Datos en memoria (sin DB para MVP)"""


class BackendAgent(BaseSpecializedAgent):
    agent_type = "backend"

    async def execute(self, task: dict) -> AgentResult:
        from core.ai_cascade import call_ai_with_fallback
        from core.actions.code_action import _parse_multi_file_response, _CODE_BLOCK_PATTERN
        import re, hashlib

        task_id = task.get("id", "backend-task")
        description = task.get("description", "")
        project_path = Path(task.get("project_path", "generated_apps/app"))
        project_path.mkdir(parents=True, exist_ok=True)

        start = int(time.monotonic() * 1000)
        try:
            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Crea el backend para: {description}"},
            ]
            response = await call_ai_with_fallback(messages)
            if isinstance(response, str) and "\n" not in response and "\\n" in response:
                response = response.replace("\\n", "\n")

            files = _parse_multi_file_response(response) or []
            if not files:
                # Fallback: extract single code block as main.py
                match = _CODE_BLOCK_PATTERN.search(response)
                if match:
                    files = [{"path": "main.py", "content": match.group(1).strip()}]

            created = []
            for f in files:
                content = _strip_fences(f["content"])
                fpath = project_path / f["path"]
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
                created.append(f["path"])

            return self._result(
                task_id=task_id, success=bool(created),
                output=f"Generated {len(created)} backend files: {created}",
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
