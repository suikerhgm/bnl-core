# core/architect/app_creator.py
"""
AppCreator — closes the gap between planning and real file generation.
Uses the existing AI cascade + file parser from code_action to generate
real runnable apps, then writes them to generated_apps/ and attempts launch.

Reuses: call_ai_with_fallback, _parse_multi_file_response, _parse_blueprint_response,
        _SYSTEM_PROMPT_GENERATE, RuntimeEngine.
No new architecture — this is pure integration glue.
"""
from __future__ import annotations
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse existing AI + file parsing from code_action
from core.actions.code_action import (
    _parse_multi_file_response,
    _parse_blueprint_response,
    _SYSTEM_PROMPT_GENERATE,
    _SYSTEM_PROMPT_BLUEPRINT,
    _CODE_BLOCK_PATTERN,
)
from core.ai_cascade import call_ai_with_fallback

GENERATED_APPS_DIR = Path("generated_apps")

_APP_SYSTEM_PROMPT = """Eres El Forjador, ingeniero senior especializado en crear aplicaciones Python funcionales.

GENERA una aplicación Python completa y funcional según la descripción del usuario.

## FORMATO OBLIGATORIO (sin excepciones):

--- FILE: main.py ---
```python
# código aquí
```

--- FILE: requirements.txt ---
```
fastapi
uvicorn
```

## REGLAS CRÍTICAS (TODAS obligatorias):
1. La app DEBE ser ejecutable con: python main.py
2. Usa FastAPI en el puerto 8080
3. main.py DEBE terminar con EXACTAMENTE este bloque:

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

4. requirements.txt DEBE incluir: fastapi y uvicorn (sin bloques ```, solo texto plano)
5. Máximo 3 archivos (main.py, requirements.txt, README.md opcional)
6. Código funcional y completo, SIN TODOs
7. Sin texto explicativo entre archivos — solo los bloques FILE
8. Datos en memoria para MVP (no base de datos)
9. CRUD completo para el recurso principal"""


@dataclass
class AppCreationResult:
    success: bool
    app_name: str
    app_path: str
    files_created: list[str]
    execution_output: str
    error: Optional[str] = None
    pid: Optional[int] = None
    port: Optional[int] = None
    execution_time_ms: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AppCreator:
    """
    Generates real runnable apps from natural language descriptions.
    Pipeline: description → AI generates code → write files → attempt launch.
    """

    async def create(self, description: str, app_name: Optional[str] = None) -> AppCreationResult:
        start = int(time.monotonic() * 1000)
        app_name = app_name or self._derive_name(description)
        app_path = GENERATED_APPS_DIR / app_name
        app_path.mkdir(parents=True, exist_ok=True)

        # Step 1: Generate code via AI cascade
        try:
            ai_response = await self._generate_code(description)
        except Exception as e:
            return AppCreationResult(
                success=False, app_name=app_name, app_path=str(app_path),
                files_created=[], execution_output="",
                error=f"AI generation failed: {e}",
                execution_time_ms=int(time.monotonic() * 1000) - start,
            )

        # Step 2: Parse multi-file response
        files = _parse_multi_file_response(ai_response)
        if not files:
            # Fallback: treat entire response as main.py
            content = _extract_single_code(ai_response)
            if content:
                files = [{"path": "main.py", "content": content}]
            else:
                return AppCreationResult(
                    success=False, app_name=app_name, app_path=str(app_path),
                    files_created=[], execution_output="",
                    error="AI returned no parseable code",
                    execution_time_ms=int(time.monotonic() * 1000) - start,
                )

        # Step 3: Write files to disk
        created = []
        for file_info in files:
            file_path = app_path / file_info["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = _clean_content(file_info["content"])
            file_path.write_text(content, encoding="utf-8")
            created.append(file_info["path"])

        # Step 4: Install dependencies if requirements.txt exists
        req_file = app_path / "requirements.txt"
        if req_file.exists():
            self._install_deps(req_file)

        # Step 5: Attempt to launch
        pid, port, exec_output = self._try_launch(app_path)

        elapsed = int(time.monotonic() * 1000) - start
        return AppCreationResult(
            success=True,
            app_name=app_name,
            app_path=str(app_path),
            files_created=created,
            execution_output=exec_output,
            pid=pid,
            port=port,
            execution_time_ms=elapsed,
        )

    async def _generate_code(self, description: str) -> str:
        messages = [
            {"role": "system", "content": _APP_SYSTEM_PROMPT},
            {"role": "user", "content": f"Crea esta aplicación: {description}"},
        ]
        response = await call_ai_with_fallback(messages)
        response = response if isinstance(response, str) else str(response)
        # Unescape literal \n sequences if the response has no real newlines
        if "\n" not in response and "\\n" in response:
            response = response.replace("\\n", "\n")
        return response

    @staticmethod
    def _derive_name(description: str) -> str:
        """Derive a filesystem-safe app name from description."""
        clean = re.sub(r"[^a-z0-9\s]", "", description.lower())
        words = clean.split()[:3]
        name = "_".join(words) if words else "app"
        return f"{name}_{int(time.time())}"

    @staticmethod
    def _install_deps(req_file: Path) -> None:
        """Install Python dependencies. Fail silently — app may still work."""
        try:
            subprocess.run(
                ["pip", "install", "-r", str(req_file), "-q", "--no-warn-script-location"],
                timeout=60,
                capture_output=True,
            )
        except Exception:
            pass

    @staticmethod
    def _try_launch(app_path: Path) -> tuple[Optional[int], Optional[int], str]:
        """
        Attempt to launch the app. Returns (pid, port, output_snippet).
        Checks syntax first, then tries to start as background process.
        """
        main_py = app_path / "main.py"
        if not main_py.exists():
            return None, None, "No main.py found"

        # Syntax check
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", str(main_py)],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                err = result.stderr.decode(errors="replace")[:500]
                return None, None, f"Syntax error: {err}"
        except Exception as e:
            return None, None, f"Syntax check failed: {e}"

        # Detect port from code
        port = _detect_port(main_py.read_text(errors="replace"))

        # Launch as background process — use main.py filename, not full path
        try:
            proc = subprocess.Popen(
                ["python", "main.py"],        # relative to app_path cwd
                cwd=str(app_path),            # launch FROM the app directory
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            # Give it 2.5s to start, read initial output
            time.sleep(2.5)
            if proc.poll() is not None:
                out = proc.stdout.read(2000).decode(errors="replace") if proc.stdout else ""
                return None, None, f"App exited immediately: {out[:300]}"
            return proc.pid, port, f"App running (pid={proc.pid})"
        except Exception as e:
            return None, None, f"Launch failed: {e}"


def _extract_single_code(text: str) -> str:
    """Extract code from a single fenced block."""
    match = _CODE_BLOCK_PATTERN.search(text)
    return match.group(1).strip() if match else text.strip()


def _clean_content(content: str) -> str:
    """
    Strip any remaining fenced code block markers (``` lang / ```) from content.
    Handles cases where the AI response parser left them in.
    """
    # Remove opening fence: ```python\n or ```\n at start
    content = re.sub(r"^```[a-zA-Z]*\s*\n?", "", content.strip())
    # Remove closing fence: ``` at end
    content = re.sub(r"\n?```\s*$", "", content)
    return content.strip()


def _detect_port(code: str) -> Optional[int]:
    """Detect port number from source code."""
    match = re.search(r"port\s*=\s*(\d{4,5})", code, re.IGNORECASE)
    if match:
        return int(match.group(1))
    for port in (8080, 8000, 5000, 3000):
        if str(port) in code:
            return port
    return None
