# core/agents/specialized/repair_agent.py
"""
RepairAgent — receives error output + source code, applies minimal fix using AI,
rewrites the file, and verifies syntax. Integrates with the auto-repair loop.
"""
from __future__ import annotations
import subprocess
import time
from pathlib import Path
from ._base import BaseSpecializedAgent, AgentResult

_SYSTEM = """Eres El Forjador, experto en depuración y reparación de código Python.

Recibirás código con errores y el mensaje de error.
Tu trabajo: arreglar SOLO el problema mínimo necesario.

FORMATO OBLIGATORIO:
--- FILE: main.py ---
```python
# código corregido
```

REGLAS:
- Corrige SOLO el error reportado
- No cambies funcionalidad no relacionada
- Código completo (no solo el fragmento)
- Sin TODOs ni comentarios de depuración"""


class RepairAgent(BaseSpecializedAgent):
    agent_type = "repair"

    async def execute(self, task: dict) -> AgentResult:
        from core.ai_cascade import call_ai_with_fallback
        from core.actions.code_action import _parse_multi_file_response, _CODE_BLOCK_PATTERN
        import re

        task_id = task.get("id", "repair-task")
        error_output = task.get("error", "")
        project_path = Path(task.get("project_path", "generated_apps/app"))
        target_file = task.get("target_file", "main.py")

        start = int(time.monotonic() * 1000)
        try:
            # Read current file
            source_file = project_path / target_file
            source_code = source_file.read_text(encoding="utf-8") if source_file.exists() else ""

            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": (
                    f"Error encontrado:\n```\n{error_output[:1000]}\n```\n\n"
                    f"Código actual de {target_file}:\n```python\n{source_code[:3000]}\n```\n\n"
                    f"Repara el error."
                )},
            ]
            response = await call_ai_with_fallback(messages)
            if isinstance(response, str) and "\n" not in response and "\\n" in response:
                response = response.replace("\\n", "\n")

            files = _parse_multi_file_response(response) or []
            if not files:
                match = _CODE_BLOCK_PATTERN.search(response)
                if match:
                    files = [{"path": target_file, "content": match.group(1).strip()}]

            repaired = []
            for f in files:
                content = _strip_fences(f["content"])
                fpath = project_path / f["path"]
                fpath.write_text(content, encoding="utf-8")
                repaired.append(f["path"])

            # Verify syntax after repair
            if repaired:
                check = subprocess.run(
                    ["python", "-m", "py_compile", target_file],
                    cwd=str(project_path), capture_output=True, timeout=10,
                )
                if check.returncode != 0:
                    err = check.stderr.decode(errors="replace")[:300]
                    return self._result(task_id=task_id, success=False,
                                        output="", error=f"Still has syntax error: {err}",
                                        files=repaired,
                                        duration_ms=int(time.monotonic() * 1000) - start)

            return self._result(
                task_id=task_id, success=bool(repaired),
                output=f"Repaired: {repaired}",
                files=repaired,
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
