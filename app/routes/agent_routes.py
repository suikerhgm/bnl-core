"""
Agent Registry API routes — /agents/*

Endpoints:
    GET /agents/status       — registry stats summary
    GET /agents/list         — full agent roster (filterable)
    GET /agents/departments  — departments with agent counts
    GET /agents/capabilities — all registered capabilities
    GET /agents/{agent_id}   — single agent detail
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from core.agents.nexus_registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status")
def agents_status():
    """[AGENT_REGISTRY] Registry-wide statistics."""
    try:
        stats = get_registry().get_stats()
        return JSONResponse({"ok": True, "stats": stats})
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list")
def agents_list(
    department: Optional[str] = Query(None, description="Filter by department_id"),
    status: Optional[str]     = Query(None, description="Filter by status (active/inactive/terminated)"),
    temporary: Optional[bool] = Query(None, description="Filter temporary agents only"),
):
    """[AGENT_REGISTRY] List agents with optional filters."""
    try:
        agents = get_registry().list_agents(
            department=department,
            status=status,
            temporary=temporary,
        )
        return JSONResponse({"ok": True, "count": len(agents), "agents": agents})
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/list error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/departments")
def agents_departments():
    """[AGENT_REGISTRY] List all departments with live agent counts."""
    try:
        departments = get_registry().list_departments()
        return JSONResponse({"ok": True, "count": len(departments), "departments": departments})
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/departments error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/capabilities")
def agents_capabilities():
    """[AGENT_REGISTRY] List all registered capabilities grouped by category."""
    try:
        caps = get_registry().list_capabilities()
        grouped: dict = {}
        for cap in caps:
            cat = cap.get("category", "general")
            grouped.setdefault(cat, []).append(cap)
        return JSONResponse({
            "ok": True,
            "count": len(caps),
            "capabilities": caps,
            "by_category": grouped,
        })
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/capabilities error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/hierarchy")
def agents_hierarchy():
    """[AGENT_REGISTRY] Return top-level agents and their children."""
    try:
        reg = get_registry()
        top_level = reg.list_agents(status="active")
        roots = [a for a in top_level if not a.get("parent_agent")]
        result = []
        for root in roots:
            children = reg.list_agents()
            children = [a for a in children if a.get("parent_agent") == root["agent_id"]]
            root["children"] = children
            result.append(root)
        return JSONResponse({"ok": True, "hierarchy": result})
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/hierarchy error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{agent_id}")
def agent_detail(agent_id: str):
    """[AGENT_REGISTRY] Fetch a single agent by ID."""
    try:
        agent = get_registry().get_agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        return JSONResponse({"ok": True, "agent": agent})
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[AGENT_REGISTRY] /agents/%s error: %s", agent_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
