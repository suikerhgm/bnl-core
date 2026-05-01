"""
Cliente HTTP para el backend FastAPI local.
Proporciona funciones para llamar a build-app y execute-plan.
"""
import os
import logging
from typing import Dict

import httpx

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _ch = logging.StreamHandler()
    _ch.setLevel(logging.INFO)
    _fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
BACKEND_HEADERS = {"Content-Type": "application/json"}


async def _call_backend(endpoint: str, payload: Dict) -> Dict:
    """Llama al backend FastAPI local (puerto 8000) con un payload JSON."""
    url = f"{BACKEND_API_URL}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=BACKEND_HEADERS)
            if response.status_code == 200:
                return response.json()
            error_body = response.text[:500]
            logger.error(f"❌ Backend {endpoint} error {response.status_code}: {error_body}")
            return {"error": f"Backend respondió {response.status_code}: {error_body}"}
    except httpx.RequestError as e:
        logger.error(f"❌ Backend {endpoint} conexión fallida: {e}")
        return {"error": f"No se pudo conectar con el backend ({BACKEND_API_URL}): {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Backend {endpoint} error inesperado: {e}")
        return {"error": f"Error al llamar al backend: {str(e)}"}


async def call_build_app(idea: str) -> Dict:
    """Llama a POST /build-app del backend para generar un plan de proyecto."""
    logger.info(f"🔨 Llamando a build_app con idea: '{idea}'")
    return await _call_backend("/build-app", {"idea": idea})


async def call_execute_plan(plan_id: str) -> Dict:
    """Llama a POST /execute-plan del backend para ejecutar un plan."""
    logger.info(f"⚡ Llamando a execute_plan con plan_id: '{plan_id}'")
    return await _call_backend("/execute-plan", {"plan_id": plan_id})
