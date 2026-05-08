# core/actions/code_action.py

import re
import logging
from typing import Dict, Any, Optional

from core.actions.base_action import BaseAction
from core.ai_cascade import call_ai_with_fallback

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────

_CODE_BLOCK_PATTERN = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
_FILE_MARKER_RE = re.compile(r"---\s*FILE:\s*(.+?)\s*---")

_AGENT_IDENTITY = "El Forjador"

_SYSTEM_PROMPT_GENERATE = f"""Eres {_AGENT_IDENTITY}, un ingeniero de software experto en:

* React Native y desarrollo mobile
* Backend APIs (FastAPI, Express, etc.)
* Arquitectura limpia (Clean Architecture, SOLID)
* Sistemas listos para producción

## FORMATO DE RESPUESTA OBLIGATORIO

Divide SIEMPRE el proyecto en múltiples archivos usando EXACTAMENTE este formato:

--- FILE: src/screens/LoginScreen.tsx ---
```tsx
// código aquí
```

--- FILE: src/config/firebase.ts ---
```ts
// código aquí
```

## REGLAS DE SEPARACIÓN DE ARCHIVOS

1. **UI / Pantallas**: `src/screens/` o `src/components/`
2. **Configuración**: `src/config/`
3. **Servicios / lógica**: `src/services/`
4. **Tipos TypeScript**: `src/types/`
5. **Hooks personalizados**: `src/hooks/`

## LINEAMIENTOS DE CÓDIGO

1. Nombres descriptivos en inglés (variables, funciones, clases)
2. TypeScript con tipos explícitos cuando el contexto lo permita
3. Manejo de errores con try/catch o Result types
4. Comentarios en español donde aporten valor real
5. Inyección de dependencias para facilitar testing
6. Componentes pequeños y con responsabilidad única

## RESTRICCIONES

- NO incluyas texto explicativo entre archivos, solo los bloques FILE
- NO omitas ningún import necesario
- Cada archivo debe ser funcional de forma independiente"""

_SYSTEM_PROMPT_REFACTOR = f"""Eres {_AGENT_IDENTITY}, un experto en refactorización de código especializado en:

* React Native y desarrollo mobile
* Backend APIs (FastAPI, Express, etc.)
* Arquitectura limpia (Clean Architecture, SOLID)
* Sistemas listos para producción

## LINEAMIENTOS DE REFACTORIZACIÓN

1. **No rompas**: Preserva la funcionalidad existente
2. **Mejora**: Aplica principios SOLID, DRY, KISS
3. **Claridad**: El código debe ser más legible que el original
4. **Rendimiento**: Identifica y optimiza cuellos de botella
5. **Seguridad**: Corrige vulnerabilidades obvias

Responde con el código refactorizado dentro de bloques ```.
Explica brevemente los cambios realizados en español antes o después del código."""

_SYSTEM_PROMPT_DEBUG = f"""Eres {_AGENT_IDENTITY}, un experto en depuración de código especializado en:

* React Native y desarrollo mobile
* Backend APIs (FastAPI, Express, etc.)
* Arquitectura limpia (Clean Architecture, SOLID)
* Sistemas listos para producción

## LINEAMIENTOS DE DEPURACIÓN

1. **Identifica**: Encuentra la causa raíz, no solo los síntomas
2. **Corrige**: Aplica la solución mínima necesaria
3. **Verifica**: El código corregido debe ser funcional
4. **Previene**: Sugiere cómo evitar errores similares

Responde con el código corregido dentro de bloques ```.
Explica brevemente los errores encontrados y cómo los solucionaste en español."""

_SYSTEM_PROMPT_BLUEPRINT = f"""Eres {_AGENT_IDENTITY}, un arquitecto de software experto.
Tu tarea es PLANIFICAR la estructura de un proyecto SIN escribir código.

Responde ÚNICAMENTE con este formato exacto — sin texto adicional:

--- PROJECT: <nombre_en_snake_case> ---
<descripción en una línea>

--- FILES ---
<ruta/relativa/archivo.ext> | <descripción en una línea>
<ruta/relativa/archivo.ext> | <descripción en una línea>

--- DEPENDENCIES ---
<paquete>
<paquete>

--- STEPS ---
1. <paso de acción>
2. <paso de acción>

## REGLAS
- Los nombres de archivo deben ser rutas relativas válidas
- Máximo 10 archivos, sólo los esenciales
- Máximo 8 dependencias
- Máximo 6 pasos
- No incluyas bloques de código, solo la estructura"""


# ── Funciones auxiliares (módulo) ─────────────────

def _extract_code(text: str) -> str:
    """
    Extrae el primer bloque de código ```...``` de un texto.
    Si no encuentra bloques, retorna el texto completo.
    """
    match = _CODE_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _build_generate_prompt(request: str, code: Optional[str] = None) -> str:
    if code:
        return f"Basándote en el siguiente código de ejemplo:\n\n```\n{code}\n```\n\nGenera el código que cumpla con: {request}"
    return f"Genera el siguiente código siguiendo los lineamientos:\n\n{request}"


def _build_refactor_prompt(request: str, code: Optional[str] = None) -> str:
    if code:
        return f"Refactoriza el siguiente código:\n\n```\n{code}\n```\n\nContexto adicional: {request}"
    return f"Refactoriza o mejora el siguiente código:\n\n{request}"


def _build_debug_prompt(request: str, code: Optional[str] = None) -> str:
    if code:
        return f"Depura el siguiente código y corrige los errores:\n\n```\n{code}\n```\n\nContexto adicional: {request}"
    return f"Depura y corrige los errores en:\n\n{request}"


_OPERATION_PROMPTS = {
    "generate": (_build_generate_prompt, _SYSTEM_PROMPT_GENERATE),
    "refactor": (_build_refactor_prompt, _SYSTEM_PROMPT_REFACTOR),
    "debug":    (_build_debug_prompt,    _SYSTEM_PROMPT_DEBUG),
}


# ── Blueprint response parsing ────────────────────────────────────
_BP_PROJECT_RE = re.compile(
    r"---\s*PROJECT:\s*(.+?)\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL
)
_BP_FILES_RE = re.compile(r"---\s*FILES\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL)
_BP_DEPS_RE = re.compile(r"---\s*DEPENDENCIES\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL)
_BP_STEPS_RE = re.compile(r"---\s*STEPS\s*---\s*\n(.+?)(?=\n---|\Z)", re.DOTALL)


def _parse_blueprint_response(text: str) -> Optional[dict]:
    """
    Parse a blueprint AI response into a structured project dict.

    Returns None if the response contains no PROJECT marker (caller should
    build a minimal fallback from the raw text).
    """
    project_match = _BP_PROJECT_RE.search(text)
    if not project_match:
        return None

    name = project_match.group(1).strip()
    description = project_match.group(2).strip().splitlines()[0]

    files: list = []
    files_match = _BP_FILES_RE.search(text)
    if files_match:
        for line in files_match.group(1).strip().splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                path, desc = line.split("|", 1)
                files.append({"path": path.strip(), "description": desc.strip()})
            else:
                files.append({"path": line, "description": ""})

    dependencies: list = []
    deps_match = _BP_DEPS_RE.search(text)
    if deps_match:
        for line in deps_match.group(1).strip().splitlines():
            dep = re.sub(r"^[-*•\s]+", "", line).strip()
            if dep:
                dependencies.append(dep)

    steps: list = []
    steps_match = _BP_STEPS_RE.search(text)
    if steps_match:
        for line in steps_match.group(1).strip().splitlines():
            step = re.sub(r"^\d+\.\s*", "", line.strip()).strip()
            if step:
                steps.append(step)

    return {
        "name": name,
        "description": description,
        "files": files,
        "dependencies": dependencies,
        "steps": steps,
    }


def _parse_multi_file_response(text: str) -> Optional[list]:
    """
    Parse an AI response that uses --- FILE: path --- markers.

    Returns a list of {"path": str, "content": str} dicts, or None if
    the response contains no FILE markers (caller should fall back to
    single-file mode).

    Example input:
        --- FILE: src/screens/Login.tsx ---
        ```tsx
        const Login = () => <View />;
        ```
        --- FILE: src/config/firebase.ts ---
        ```ts
        export const app = initializeApp(config);
        ```
    """
    parts = _FILE_MARKER_RE.split(text)
    # split() with a capture group yields:
    #   [pre_text, path1, body1, path2, body2, ...]
    if len(parts) < 3:
        return None

    files = []
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        path = parts[i].strip()
        raw_body = parts[i + 1].strip()

        # Extract code from fenced block if present; otherwise use raw text
        code_match = _CODE_BLOCK_PATTERN.search(raw_body)
        content = code_match.group(1).strip() if code_match else raw_body

        if path and content:
            files.append({"path": path, "content": content})

    return files if files else None


def _build_prompt(operation: str, request: str, code: Optional[str] = None) -> list:
    """
    Construye la lista de mensajes [system, user] para call_ai_with_fallback.
    """
    prompt_builder, system_prompt = _OPERATION_PROMPTS.get(
        operation,
        (_build_generate_prompt, _SYSTEM_PROMPT_GENERATE),
    )
    user_content = prompt_builder(request, code)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ]


# ── Clase CodeAction ──────────────────────────────

class CodeAction(BaseAction):
    """
    Ejecutor de acciones sobre código fuente mediante IA.

    Identidad: El Forjador — un ingeniero de software experto.

    Operaciones soportadas:
    - generate: Generar código nuevo
    - refactor: Refactorizar código existente
    - debug: Depurar y corregir código
    - lint: (No implementado)
    - format: (No implementado)
    """

    AGENT_NAME = _AGENT_IDENTITY

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        self.operation: str = context.get("operation", "generate")
        self.params: Dict[str, Any] = context.get("params", {})
        self.decision_trace: Dict[str, Any] = context.get("decision_trace", {})

    async def execute(self) -> Dict[str, Any]:
        """
        Ejecuta la operación de código usando IA.

        Returns:
            Dict con formato:
            {
                "success": bool,
                "result": Any,       # Código generado/refactorizado/depurado
                "error": Optional[str],
                "metadata": Dict     # Solo cuando success=True
            }
        """
        # ── Operaciones no implementadas ──
        if self.operation in ("lint", "format"):
            logger.warning(f"⚠️ CodeAction.{self.operation} not implemented yet")
            return {
                "success": False,
                "result": None,
                "error": f"CodeAction.{self.operation} no implementado",
            }

        # ── Extraer solicitud del usuario ──
        request = self._extract_user_request()
        if not request:
            logger.warning("⚠️ CodeAction: No se pudo extraer solicitud del usuario")
            return {
                "success": False,
                "result": None,
                "error": "No se encontró una solicitud de código válida",
            }

        logger.info(
            f"🔄 CodeAction.{self.operation}: "
            f"Solicitud recibida: '{request[:80]}...'"
        )

        # ── Blueprint mode: plan only, no code generation ─────────────
        if self.operation == "generate" and self.params.get("mode") == "blueprint":
            return await self._execute_blueprint(request)

        # ── Construir prompts ──
        code_input = self.params.get("code") or self.params.get("existing_code")
        messages = _build_prompt(self.operation, request, code_input)

        # ── Llamar a la IA ──
        try:
            response_dict, api_index = await call_ai_with_fallback(messages)
        except Exception as e:
            logger.error(f"❌ CodeAction: Fallo al llamar a la IA: {e}")
            return {
                "success": False,
                "result": None,
                "error": f"Error al llamar a la IA: {str(e)}",
            }

        # ── Extraer contenido de la respuesta ──
        raw_content = response_dict.get("content", "") or ""
        if not raw_content:
            logger.error("❌ CodeAction: Respuesta vacía de la IA")
            return {
                "success": False,
                "result": None,
                "error": "La IA retornó una respuesta vacía",
            }

        provider = response_dict.get("provider", "desconocido")

        if self.operation == "generate":
            # Attempt structured multi-file parse first
            files = _parse_multi_file_response(raw_content)
            if files:
                for f in files:
                    f["agent"] = "frontend"
                result = {"files": files}
                logger.info(
                    f"✅ CodeAction.generate completado — {len(files)} archivo(s) "
                    f"(provider: {provider})"
                )
            else:
                # Fallback: wrap single extracted block as one-file list
                code = _extract_code(raw_content)
                result = {"files": [{"path": "output.tsx", "content": code, "agent": "frontend"}]}
                logger.info(
                    f"✅ CodeAction.generate completado — 1 archivo (fallback single-block) "
                    f"(provider: {provider}, chars: {len(code)})"
                )
        else:
            # refactor / debug — keep as plain string (single file context)
            result = _extract_code(raw_content) if "```" in raw_content else raw_content
            logger.info(
                f"✅ CodeAction.{self.operation} completado "
                f"(provider: {provider}, chars: {len(result)})"
            )

        return {
            "success": True,
            "result": result,
            "error": None,
            "metadata": {
                "agent": "ElForjador",
                "operation": self.operation,
            },
        }

    async def _execute_blueprint(self, request: str) -> Dict[str, Any]:
        """
        Plan the project structure using AI without generating any code.

        Calls the AI with the blueprint system prompt, parses the structured
        response, and returns a result dict with mode="blueprint".
        """
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT_BLUEPRINT},
            {"role": "user", "content": f"Planifica el proyecto para: {request}"},
        ]

        try:
            response_dict, _ = await call_ai_with_fallback(messages)
        except Exception as e:
            logger.error("❌ CodeAction.blueprint: AI call failed: %s", e)
            return {"success": False, "result": None, "error": f"Error al planificar: {e}"}

        raw = response_dict.get("content", "") or ""
        provider = response_dict.get("provider", "desconocido")

        if not raw:
            return {"success": False, "result": None, "error": "La IA retornó una respuesta vacía"}

        project = _parse_blueprint_response(raw)

        if project is None:
            # Fallback: build a minimal structure from the raw text
            logger.warning("⚠️ CodeAction.blueprint: could not parse structured response — using fallback")
            project = {
                "name": "proyecto",
                "description": request[:120],
                "files": [],
                "dependencies": [],
                "steps": [line.strip() for line in raw.splitlines() if line.strip()][:6],
            }

        logger.info(
            "✅ CodeAction.blueprint completado — %d archivo(s) planificados (provider: %s)",
            len(project["files"]), provider,
        )

        return {
            "success": True,
            "result": {"mode": "blueprint", "project": project},
            "error": None,
            "metadata": {"agent": "ElForjador", "operation": "blueprint"},
        }

    def _extract_user_request(self) -> Optional[str]:
        """
        Extrae la solicitud del usuario desde múltiples fuentes posibles.

        Orden de búsqueda:
        1. params.get("request") o params.get("query")
        2. decision_trace (campo "user_message" o "message")
        3. context["params"]["request"]
        """
        # 1. Parámetros directos
        request = (
            self.params.get("request")
            or self.params.get("query")
            or self.params.get("prompt")
        )
        if request:
            return str(request).strip()

        # 2. Traza de decisión
        if self.decision_trace:
            request = (
                self.decision_trace.get("user_message")
                or self.decision_trace.get("message")
                or self.decision_trace.get("request")
            )
            if request:
                return str(request).strip()

        # 3. Fallback: contexto general
        request = self.context.get("request") or self.context.get("message")
        if request:
            return str(request).strip()

        return None

    def requires_approval(self) -> bool:
        """
        Operaciones destructivas o modificativas requieren aprobación.

        - generate: False (creación de código nuevo, autónomo)
        - refactor: True (modifica código existente)
        - debug: True (modifica código existente)
        - lint/format: False (análisis, sin cambios)
        """
        return self.operation in ("refactor", "debug")

    def get_description(self) -> str:
        """Descripción legible de la acción."""
        descriptions = {
            "generate": "Generar nuevo código a partir de una descripción",
            "refactor": "Refactorizar código existente para mejorarlo",
            "debug":    "Depurar y corregir errores en código",
            "lint":     "Analizar código con linter (no implementado)",
            "format":   "Formatear código (no implementado)",
        }
        desc = descriptions.get(self.operation, "Operación de código")
        return f"ElForjador.{self.operation}: {desc}"
