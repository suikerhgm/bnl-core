"""
Sandbox API routes — /sandbox/*

Endpoints:
    GET  /sandbox/status              — system-wide sandbox stats
    GET  /sandbox/list                — list all sandboxes (filterable)
    GET  /sandbox/{id}                — single sandbox detail
    GET  /sandbox/{id}/monitor        — live status + latest snapshot
    GET  /sandbox/{id}/events         — event log for a sandbox
    GET  /sandbox/{id}/violations     — violation log for a sandbox
    GET  /sandbox/{id}/snapshots      — resource snapshot history
    GET  /sandbox/{id}/export         — full forensic export
    POST /sandbox/create              — create sandbox (no execution)
    POST /sandbox/execute             — create + execute in sandbox
    POST /sandbox/{id}/freeze         — freeze (suspend) sandbox
    POST /sandbox/{id}/quarantine     — manually quarantine
    POST /sandbox/{id}/destroy        — destroy and clean up
    GET  /sandbox/modes               — list available sandbox modes
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.sandbox.sandbox_manager import get_sandbox_manager
from core.sandbox.sandbox_environment import SandboxMode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateRequest(BaseModel):
    agent_id: Optional[str] = None
    mode:     str           = "RESTRICTED_EXECUTION"
    metadata: Optional[Dict] = None

class ExecuteRequest(BaseModel):
    command:     List[str]
    mode:        str           = "RESTRICTED_EXECUTION"
    agent_id:    Optional[str] = None
    input_files: Optional[Dict[str, str]] = None
    timeout:     Optional[float] = None
    env_vars:    Optional[Dict[str, str]] = None

class QuarantineRequest(BaseModel):
    reason: str = "manual_quarantine"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status")
def sandbox_status():
    """[SANDBOX] System-wide sandbox statistics."""
    try:
        return JSONResponse({"ok": True, "stats": get_sandbox_manager().get_stats()})
    except Exception as exc:
        logger.error("[SANDBOX] /sandbox/status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/modes")
def sandbox_modes():
    """[SANDBOX] List all available sandbox modes with their configurations."""
    from core.sandbox.sandbox_environment import MODE_CONFIG
    modes = {
        mode.value: {k: str(v) if not isinstance(v, (int, float, bool)) else v
                     for k, v in cfg.items()}
        for mode, cfg in MODE_CONFIG.items()
    }
    return JSONResponse({"ok": True, "modes": modes})


@router.get("/list")
def sandbox_list(
    status:   Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    limit:    int            = Query(50, le=200),
):
    """[SANDBOX] List sandboxes with optional filters."""
    try:
        sandboxes = get_sandbox_manager().list_sandboxes(
            status=status, agent_id=agent_id, limit=limit
        )
        return JSONResponse({"ok": True, "count": len(sandboxes), "sandboxes": sandboxes})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}/monitor")
def sandbox_monitor(sandbox_id: str):
    """[SANDBOX] Live status + latest resource snapshot."""
    try:
        data = get_sandbox_manager().monitor_sandbox(sandbox_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
        return JSONResponse({"ok": True, **data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}/events")
def sandbox_events(
    sandbox_id: str,
    severity: Optional[str] = Query(None),
    limit:    int            = Query(200, le=1000),
):
    """[SANDBOX] Event log for a sandbox."""
    try:
        from core.sandbox.sandbox_audit_logger import get_audit_logger
        events = get_audit_logger().get_events(sandbox_id, severity=severity, limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}/violations")
def sandbox_violations(sandbox_id: str):
    """[SANDBOX] Violation log for a sandbox."""
    try:
        from core.sandbox.sandbox_audit_logger import get_audit_logger
        violations = get_audit_logger().get_violations(sandbox_id)
        return JSONResponse({"ok": True, "count": len(violations), "violations": violations})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}/snapshots")
def sandbox_snapshots(
    sandbox_id: str,
    limit:      int = Query(60, le=500),
):
    """[SANDBOX] Resource snapshot history."""
    try:
        from core.sandbox.sandbox_audit_logger import get_audit_logger
        snaps = get_audit_logger().get_snapshots(sandbox_id, limit=limit)
        return JSONResponse({"ok": True, "count": len(snaps), "snapshots": snaps})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}/export")
def sandbox_export(sandbox_id: str):
    """[SANDBOX] Full forensic export for a sandbox."""
    try:
        data = get_sandbox_manager().export_sandbox_logs(sandbox_id)
        if not data.get("sandbox"):
            raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
        return JSONResponse({"ok": True, **data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{sandbox_id}")
def sandbox_detail(sandbox_id: str):
    """[SANDBOX] Single sandbox record."""
    try:
        data = get_sandbox_manager().get_sandbox(sandbox_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
        return JSONResponse({"ok": True, "sandbox": data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Write endpoints ────────────────────────────────────────────────────────────

@router.post("/create")
def sandbox_create(body: CreateRequest):
    """[SANDBOX] Create a new sandbox environment (no execution)."""
    try:
        env = get_sandbox_manager().create_sandbox(
            agent_id=body.agent_id,
            mode=body.mode,
            metadata=body.metadata,
        )
        return JSONResponse({
            "ok": True,
            "sandbox_id":    env.sandbox_id,
            "mode":          env.mode.value,
            "workspace":     str(env.workspace_path),
            "status":        env.status.value,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/execute")
async def sandbox_execute(body: ExecuteRequest):
    """[SANDBOX] Execute a command inside a sandbox and return the result."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_sandbox_manager().execute_in_sandbox(
                command=body.command,
                mode=body.mode,
                agent_id=body.agent_id,
                input_files=body.input_files,
                timeout=body.timeout,
                env_vars=body.env_vars,
            ),
        )
        return JSONResponse({"ok": True, **result})
    except Exception as exc:
        logger.error("[SANDBOX] /sandbox/execute error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{sandbox_id}/freeze")
def sandbox_freeze(sandbox_id: str):
    """[SANDBOX] Freeze (suspend) a running sandbox."""
    try:
        ok = get_sandbox_manager().freeze_sandbox(sandbox_id)
        return JSONResponse({"ok": ok, "sandbox_id": sandbox_id, "frozen": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{sandbox_id}/quarantine")
def sandbox_quarantine(sandbox_id: str, body: QuarantineRequest):
    """[SANDBOX] Manually quarantine a sandbox."""
    try:
        ok = get_sandbox_manager().quarantine_sandbox(sandbox_id, reason=body.reason)
        return JSONResponse({"ok": ok, "sandbox_id": sandbox_id, "quarantined": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{sandbox_id}/destroy")
def sandbox_destroy(sandbox_id: str):
    """[SANDBOX] Destroy and clean up a sandbox."""
    try:
        ok = get_sandbox_manager().destroy_sandbox(sandbox_id)
        return JSONResponse({"ok": ok, "sandbox_id": sandbox_id, "destroyed": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
