"""
Isolation API routes — /isolation/*

Endpoints:
    GET  /isolation/status                  — system-wide stats
    GET  /isolation/processes               — all isolated process records
    GET  /isolation/violations              — runtime violations log
    GET  /isolation/emergency               — emergency events log
    GET  /isolation/levels                  — isolation level profiles
    GET  /isolation/{id}                    — single process detail
    GET  /isolation/{id}/history            — resource usage history
    GET  /isolation/{id}/violations         — violations for one process
    POST /isolation/isolate                 — register a PID in isolation
    POST /isolation/{id}/freeze             — freeze a process
    POST /isolation/{id}/unfreeze           — resume a frozen process
    POST /isolation/{id}/destroy            — destroy isolation environment
    POST /isolation/{id}/limit/cpu          — update CPU limit
    POST /isolation/{id}/limit/memory       — update memory limit
    POST /isolation/kill/{pid}              — emergency kill a PID
    POST /isolation/emergency_shutdown      — LOCKDOWN the whole system
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.isolation.isolation_manager import get_isolation_manager
from core.isolation.resource_limiter import LEVEL_LIMITS, IsolationLevel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/isolation", tags=["isolation"])


# ── Request bodies ─────────────────────────────────────────────────────────────

class IsolateRequest(BaseModel):
    pid:            int
    agent_id:       Optional[str] = None
    level:          str           = "RESTRICTED"
    workspace_root: str           = "."
    custom_limits:  Optional[Dict[str, Any]] = None

class KillRequest(BaseModel):
    reason: str = "manual_kill"

class ShutdownRequest(BaseModel):
    reason: str

class LimitRequest(BaseModel):
    value: float


# ── Read endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
def isolation_status():
    """[ISOLATION] System-wide isolation statistics."""
    try:
        return JSONResponse({"ok": True, "stats": get_isolation_manager().get_stats()})
    except Exception as exc:
        logger.error("[ISOLATION] /isolation/status: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/levels")
def isolation_levels():
    """[ISOLATION] List all isolation level profiles with their default limits."""
    profiles = {
        level.value: limits
        for level, limits in LEVEL_LIMITS.items()
    }
    return JSONResponse({"ok": True, "levels": profiles})


@router.get("/processes")
def isolation_processes(
    status: Optional[str] = Query(None, description="active / frozen / quarantined / destroyed"),
    limit:  int           = Query(50, le=200),
):
    """[ISOLATION] List all isolated process records."""
    try:
        procs = get_isolation_manager().list_isolated_processes(status=status, limit=limit)
        return JSONResponse({"ok": True, "count": len(procs), "processes": procs})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/violations")
def isolation_violations(
    process_id: Optional[str] = Query(None),
    limit:      int           = Query(100, le=500),
):
    """[ISOLATION] Runtime violations log."""
    try:
        viols = get_isolation_manager().list_violations(process_id=process_id, limit=limit)
        return JSONResponse({"ok": True, "count": len(viols), "violations": viols})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/emergency")
def isolation_emergency(limit: int = Query(50, le=200)):
    """[ISOLATION] Emergency events log."""
    try:
        events = get_isolation_manager().list_emergency_events(limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{process_id}/history")
def isolation_history(
    process_id: str,
    limit:      int = Query(60, le=500),
):
    """[ISOLATION] Resource usage history for one process."""
    try:
        history = get_isolation_manager().get_resource_history(process_id, limit=limit)
        return JSONResponse({"ok": True, "count": len(history), "history": history})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{process_id}/violations")
def isolation_process_violations(process_id: str):
    """[ISOLATION] Violations for a single process."""
    try:
        viols = get_isolation_manager().list_violations(process_id=process_id)
        return JSONResponse({"ok": True, "count": len(viols), "violations": viols})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{process_id}")
def isolation_detail(process_id: str):
    """[ISOLATION] Live status for one isolated process."""
    try:
        data = get_isolation_manager().monitor_runtime_behavior(process_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Process '{process_id}' not found")
        return JSONResponse({"ok": True, **data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Write endpoints ────────────────────────────────────────────────────────────

@router.post("/isolate")
def isolation_isolate(body: IsolateRequest):
    """[ISOLATION] Register a PID in the isolation system."""
    try:
        ctx = get_isolation_manager().isolate_process(
            pid=body.pid,
            agent_id=body.agent_id,
            level=body.level,
            workspace_root=body.workspace_root,
            custom_limits=body.custom_limits,
        )
        return JSONResponse({
            "ok": True,
            "process_id": ctx.process_id,
            "pid":        ctx.pid,
            "level":      ctx.level.value,
            "status":     ctx.status,
        })
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("[ISOLATION] /isolation/isolate: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{process_id}/freeze")
def isolation_freeze(process_id: str):
    """[ISOLATION] Freeze (suspend) an isolated process."""
    try:
        ok = get_isolation_manager().freeze_isolated_process(process_id)
        return JSONResponse({"ok": ok, "process_id": process_id, "frozen": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{process_id}/unfreeze")
def isolation_unfreeze(process_id: str):
    """[ISOLATION] Resume a frozen isolated process."""
    try:
        ok = get_isolation_manager().unfreeze_isolated_process(process_id)
        return JSONResponse({"ok": ok, "process_id": process_id, "resumed": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{process_id}/destroy")
def isolation_destroy(process_id: str):
    """[ISOLATION] Destroy an isolation environment (kills process + closes job)."""
    try:
        ok = get_isolation_manager().destroy_isolation_environment(process_id)
        return JSONResponse({"ok": ok, "process_id": process_id, "destroyed": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{process_id}/limit/cpu")
def isolation_limit_cpu(process_id: str, body: LimitRequest):
    """[ISOLATION] Update CPU limit for an active isolation."""
    try:
        ok = get_isolation_manager().limit_cpu_usage(process_id, body.value)
        return JSONResponse({"ok": ok, "cpu_limit_percent": body.value})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{process_id}/limit/memory")
def isolation_limit_memory(process_id: str, body: LimitRequest):
    """[ISOLATION] Update memory limit for an active isolation."""
    try:
        ok = get_isolation_manager().limit_memory_usage(process_id, body.value)
        return JSONResponse({"ok": ok, "memory_limit_mb": body.value})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/kill/{pid}")
def isolation_kill(pid: int, body: KillRequest):
    """[ISOLATION] Immediately kill a process tree by PID."""
    try:
        ok = get_isolation_manager().kill_suspicious_process(pid, body.reason)
        return JSONResponse({"ok": ok, "pid": pid, "killed": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/emergency_shutdown")
def isolation_emergency_shutdown(body: ShutdownRequest):
    """[EMERGENCY] Trigger system-wide LOCKDOWN."""
    try:
        get_isolation_manager().emergency_shutdown(body.reason)
        return JSONResponse({"ok": True, "lockdown": True, "reason": body.reason})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
