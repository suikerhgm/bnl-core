# core/actions/backend_action.py

import logging
from typing import Dict, Any, Optional

from core.actions.base_action import BaseAction
from core.ai_cascade import call_ai_with_fallback
from core.actions.code_action import (
    _extract_code,
    _parse_multi_file_response,
)

logger = logging.getLogger(__name__)

_AGENT_IDENTITY = "Arquitecto"

_SYSTEM_PROMPT_BACKEND = f"""Eres {_AGENT_IDENTITY}, un ingeniero de backend experto en:

* FastAPI y Python backend
* REST APIs con autenticación JWT
* Arquitectura limpia (Clean Architecture, SOLID)
* Bases de datos (PostgreSQL, SQLite)
* Sistemas listos para producción

## FORMATO DE RESPUESTA OBLIGATORIO

Divide SIEMPRE el proyecto en múltiples archivos usando EXACTAMENTE este formato:

--- FILE: backend/main.py ---
```python
# código aquí
```

--- FILE: backend/routes/auth.py ---
```python
# código aquí
```

## REGLAS DE SEPARACIÓN DE ARCHIVOS

1. **Entrypoint**: `backend/main.py`
2. **Rutas / endpoints**: `backend/routes/`
3. **Modelos de datos**: `backend/models/`
4. **Esquemas Pydantic**: `backend/schemas/`
5. **Servicios / lógica**: `backend/services/`
6. **Configuración**: `backend/config.py`

## LINEAMIENTOS DE CÓDIGO

1. FastAPI con tipos Pydantic explícitos
2. JWT auth con python-jose
3. SQLAlchemy para ORM
4. Manejo de errores con HTTPException
5. Comentarios en español donde aporten valor

## RESTRICCIONES

- NO incluyas texto explicativo entre archivos, solo los bloques FILE
- NO omitas ningún import necesario
- Cada archivo debe ser funcional de forma independiente
- Prefija SIEMPRE las rutas con `backend/`"""


class BackendAction(BaseAction):
    """
    Genera código backend (FastAPI) como agente independiente.

    Identidad: Arquitecto — experto en APIs y arquitectura backend.
    """

    AGENT_NAME = _AGENT_IDENTITY

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        self.params: Dict[str, Any] = context.get("params", {})

    async def execute(self) -> Dict[str, Any]:
        request = (
            self.params.get("request")
            or self.params.get("query")
            or self.params.get("prompt")
            or ""
        )
        request = str(request).strip()

        if not request:
            return {"success": False, "result": None, "error": "No se encontró solicitud"}

        logger.info("🏗️ BackendAction: generando backend para '%s...'", request[:80])

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT_BACKEND},
            {"role": "user", "content": f"Construye el backend para: {request}"},
        ]

        try:
            response_dict, _ = await call_ai_with_fallback(messages)
        except Exception as e:
            logger.error("❌ BackendAction: AI call failed: %s", e)
            return {"success": False, "result": None, "error": f"Error al generar backend: {e}"}

        raw = response_dict.get("content", "") or ""
        provider = response_dict.get("provider", "desconocido")

        if not raw:
            return {"success": False, "result": None, "error": "La IA retornó una respuesta vacía"}

        files = _parse_multi_file_response(raw)
        if files:
            for f in files:
                f["agent"] = "backend"
            logger.info(
                "✅ BackendAction: %d archivo(s) generados (provider: %s)",
                len(files), provider,
            )
        else:
            # Fallback: wrap single code block as main.py
            code = _extract_code(raw)
            files = [{"path": "backend/main.py", "content": code, "agent": "backend"}]
            logger.info(
                "✅ BackendAction: 1 archivo (fallback single-block, provider: %s)", provider
            )

        return {
            "success": True,
            "result": {"files": files},
            "error": None,
            "metadata": {"agent": _AGENT_IDENTITY, "operation": "generate"},
        }

    def requires_approval(self) -> bool:
        return False

    def get_description(self) -> str:
        return f"{_AGENT_IDENTITY}: Generar backend API (FastAPI)"
