# core/agents/specialized/testing_agent.py
"""
TestingAgent — generates pytest tests for the given backend/project.
Runs the tests using subprocess and reports pass/fail.
"""
from __future__ import annotations
import subprocess
import time
from pathlib import Path
from ._base import BaseSpecializedAgent, AgentResult

_SYSTEM = """Eres El Forjador, experto en testing Python con pytest y httpx.

Genera tests FUNCIONALES para el backend dado usando pytest + httpx.

FORMATO OBLIGATORIO:
--- FILE: test_app.py ---
```python
import pytest
from httpx import AsyncClient
...
```

REGLAS:
- Usa httpx AsyncClient para probar los endpoints
- Base URL: http://localhost:8080
- Incluye al menos 3 tests (GET, POST, error case)
- Sin mocks — tests de integración reales
- Código completo y funcional"""


class TestingAgent(BaseSpecializedAgent):
    agent_type = "testing"

    async def execute(self, task: dict) -> AgentResult:
        from core.ai_cascade import call_ai_with_fallback
        from core.actions.code_action import _parse_multi_file_response, _CODE_BLOCK_PATTERN
        import re

        task_id = task.get("id", "testing-task")
        description = task.get("description", "")
        project_path = Path(task.get("project_path", "generated_apps/app"))
        run_tests = task.get("run_tests", False)

        start = int(time.monotonic() * 1000)
        try:
            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Genera tests para: {description}"},
            ]
            response = await call_ai_with_fallback(messages)
            if isinstance(response, str) and "\n" not in response and "\\n" in response:
                response = response.replace("\\n", "\n")

            files = _parse_multi_file_response(response) or []
            if not files:
                match = _CODE_BLOCK_PATTERN.search(response)
                if match:
                    files = [{"path": "test_app.py", "content": match.group(1).strip()}]

            created = []
            for f in files:
                content = _strip_fences(f["content"])
                fpath = project_path / f["path"]
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
                created.append(f["path"])

            test_output = ""
            if run_tests and created:
                try:
                    result = subprocess.run(
                        ["python", "-m", "pytest", created[0], "-v", "--tb=short"],
                        cwd=str(project_path),
                        capture_output=True, timeout=30,
                    )
                    test_output = result.stdout.decode(errors="replace")[-500:]
                except Exception as te:
                    test_output = f"Test run error: {te}"

            return self._result(
                task_id=task_id, success=bool(created),
                output=f"Generated tests: {created}\n{test_output}",
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
