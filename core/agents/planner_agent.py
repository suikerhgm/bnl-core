"""
PlannerAgent — generates project blueprints only.

Responsibilities:
- Call the AI with a structured blueprint prompt
- Return a plan split into frontend / backend sections
- NEVER write files
- NEVER execute actions
"""
import re
import logging
from typing import Dict, Any, List, Optional

from core.ai_cascade import call_ai_with_fallback
from core.actions.code_action import _BP_PROJECT_RE, _BP_DEPS_RE, _BP_STEPS_RE

logger = logging.getLogger(__name__)

# ── Blueprint V2 prompt — produces FRONTEND / BACKEND sections ─────────────

_SYSTEM_PROMPT_BLUEPRINT_V2 = """Eres un arquitecto de software experto.
Tu tarea es PLANIFICAR la estructura de un proyecto separando frontend y backend.

Responde ÚNICAMENTE con este formato exacto — sin texto adicional:

--- PROJECT: <nombre_en_snake_case> ---
<descripción en una línea>

--- FRONTEND ---
<ruta/relativa/archivo.ext> | <descripción en una línea>
<ruta/relativa/archivo.ext> | <descripción en una línea>

--- BACKEND ---
<ruta/relativa/archivo.ext> | <descripción en una línea>
<ruta/relativa/archivo.ext> | <descripción en una línea>

--- DEPENDENCIES ---
<paquete>
<paquete>

--- STEPS ---
1. <paso de acción>
2. <paso de acción>

REGLAS:
- Si el proyecto no necesita backend, deja la sección BACKEND con solo el encabezado
- Si no necesita frontend, deja FRONTEND con solo el encabezado
- Máximo 6 archivos por sección
- Máximo 8 dependencias en total
- Máximo 6 pasos
- No incluyas bloques de código, solo la estructura"""

# ── Section parsers ────────────────────────────────────────────────────────

_BP_FRONTEND_RE = re.compile(r"---\s*FRONTEND\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL)
_BP_BACKEND_RE = re.compile(r"---\s*BACKEND\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL)


def _parse_file_lines(raw: str) -> List[Dict[str, str]]:
    files = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            path, desc = line.split("|", 1)
            files.append({"path": path.strip(), "description": desc.strip()})
        else:
            files.append({"path": line, "description": ""})
    return files


def _parse_blueprint_v2(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a V2 blueprint response into a project dict with frontend/backend split.
    Returns None if the PROJECT marker is missing.
    """
    project_match = _BP_PROJECT_RE.search(text)
    if not project_match:
        return None

    name = project_match.group(1).strip()
    description = project_match.group(2).strip().splitlines()[0]

    frontend: List[Dict[str, str]] = []
    fe_match = _BP_FRONTEND_RE.search(text)
    if fe_match:
        frontend = _parse_file_lines(fe_match.group(1))

    backend: List[Dict[str, str]] = []
    be_match = _BP_BACKEND_RE.search(text)
    if be_match:
        backend = _parse_file_lines(be_match.group(1))

    dependencies: List[str] = []
    deps_match = _BP_DEPS_RE.search(text)
    if deps_match:
        for line in deps_match.group(1).strip().splitlines():
            dep = re.sub(r"^[-*•\s]+", "", line).strip()
            if dep:
                dependencies.append(dep)

    steps: List[str] = []
    steps_match = _BP_STEPS_RE.search(text)
    if steps_match:
        for line in steps_match.group(1).strip().splitlines():
            step = re.sub(r"^\d+\.\s*", "", line.strip()).strip()
            if step:
                steps.append(step)

    return {
        "name": name,
        "description": description,
        "frontend": frontend,
        "backend": backend,
        "dependencies": dependencies,
        "steps": steps,
    }


class PlannerAgent:
    """
    Blueprint-only agent that produces structured project plans.

    Output separates files into frontend and backend sections so that
    the build phase can dispatch independent agents for each layer.
    """

    AGENT_NAME = "PlannerAgent"

    def __init__(self, request: str):
        self.request = request

    async def execute(self) -> Dict[str, Any]:
        """
        Generate a frontend/backend-split blueprint for the given request.

        Returns:
            {
                "success": bool,
                "result": {
                    "mode": "blueprint",
                    "project": {
                        "name": str,
                        "description": str,
                        "frontend": [{"path": str, "description": str}, ...],
                        "backend":  [{"path": str, "description": str}, ...],
                        "dependencies": [str, ...],
                        "steps": [str, ...]
                    }
                },
                "error": Optional[str]
            }
        """
        if not self.request or not self.request.strip():
            return {"success": False, "result": None, "error": "Empty request"}

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT_BLUEPRINT_V2},
            {"role": "user", "content": f"Planifica el proyecto para: {self.request}"},
        ]

        try:
            response_dict, _ = await call_ai_with_fallback(messages)
        except Exception as e:
            logger.error("❌ PlannerAgent: AI call failed: %s", e)
            return {"success": False, "result": None, "error": f"Error al planificar: {e}"}

        raw = response_dict.get("content", "") or ""
        provider = response_dict.get("provider", "desconocido")

        if not raw:
            return {"success": False, "result": None, "error": "La IA retornó una respuesta vacía"}

        project = _parse_blueprint_v2(raw)

        if project is None:
            logger.warning("⚠️ PlannerAgent: could not parse V2 response — using fallback")
            project = {
                "name": "proyecto",
                "description": self.request[:120],
                "frontend": [],
                "backend": [],
                "dependencies": [],
                "steps": [line.strip() for line in raw.splitlines() if line.strip()][:6],
            }

        fe_count = len(project.get("frontend", []))
        be_count = len(project.get("backend", []))
        logger.info(
            "✅ PlannerAgent: blueprint ready — frontend=%d backend=%d (provider: %s)",
            fe_count, be_count, provider,
        )

        return {
            "success": True,
            "result": {
                "mode": "blueprint",
                "project": project,
            },
            "error": None,
        }
