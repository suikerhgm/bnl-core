"""
NexusAgentes — Rutas de Build App (Nexus BNL)
"""
import uuid

from fastapi import APIRouter, HTTPException

from app.config import logger
from models.schemas import (
    BuildAppRequest,
    PlanResponse,
    ExecutePlanRequest,
    ExecutePlanResponse,
)
from services.build_service import plan_project, execute_task

router = APIRouter(tags=["Build App"])

# Almacenamiento en memoria de planes generados
plans: dict = {}


@router.post(
    "/build-app",
    response_model=PlanResponse,
)
async def build_app_endpoint(request: BuildAppRequest):
    """
    Endpoint NEXUS BNL: genera el PLAN de un proyecto sin ejecutar nada.

    Acepta 'project_name' o 'idea' en lenguaje natural.
    Pipeline: Notion search → blueprint → task planner → plan pendiente de aprobación.
    """
    # Unificar input: aceptar tanto 'project_name' como 'idea'
    project_name = request.project_name or request.idea

    if not project_name:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar 'idea' o 'project_name'",
        )

    logger.info(
        f"POST /build-app | project_name='{project_name}'"
    )

    try:
        plan_data = plan_project(project_name)

        plan_id = str(uuid.uuid4())

        plans[plan_id] = {
            "blueprint": plan_data["blueprint"],
            "tasks": plan_data["tasks"],
            "status": "pending_approval",
        }

        logger.info(
            f"POST /build-app | 200 OK | "
            f"plan_id='{plan_id}' | "
            f"{len(plan_data['tasks'])} tareas planificadas"
        )

        return PlanResponse(
            plan_id=plan_id,
            status="pending_approval",
            blueprint=plan_data["blueprint"],
            tasks=plan_data["tasks"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error inesperado en /build-app: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/execute-plan",
    response_model=ExecutePlanResponse,
)
async def execute_plan_endpoint(request: ExecutePlanRequest):
    """
    Endpoint NEXUS BNL: ejecuta las tareas de un plan generado previamente.

    Toma un plan_id, valida que exista y esté pendiente,
    ejecuta todas las tareas y retorna los prompts generados.
    """
    plan_id = request.plan_id
    logger.info(f"POST /execute-plan | plan_id='{plan_id}'")

    # Buscar el plan
    if plan_id not in plans:
        raise HTTPException(
            status_code=404,
            detail="Plan no encontrado",
        )

    plan = plans[plan_id]

    # Validar estado
    if plan["status"] != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail="El plan ya fue ejecutado o no está listo",
        )

    # Cambiar estado a running
    plan["status"] = "running"

    # Ejecutar tareas una por una
    results = []
    for task in plan["tasks"]:
        result = execute_task(task)
        results.append(result)

    # Guardar resultados y marcar completado
    plan["results"] = results
    plan["status"] = "completed"

    logger.info(
        f"POST /execute-plan | 200 OK | "
        f"plan_id='{plan_id}' | "
        f"{len(results)} tareas ejecutadas"
    )

    return ExecutePlanResponse(
        plan_id=plan_id,
        status="completed",
        results=results,
    )
