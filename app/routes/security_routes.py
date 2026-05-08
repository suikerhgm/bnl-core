"""
Security API routes — /security/*

Endpoints:
    GET  /security/status               — system-wide security stats
    GET  /security/permissions          — all permissions for an agent (or catalog)
    GET  /security/events               — security event log
    GET  /security/violations           — open policy violations
    GET  /security/isolated             — currently isolated agents
    GET  /security/logs                 — permission audit log
    GET  /security/threat/{agent_id}    — threat level for one agent
    GET  /security/catalog              — full permission catalog
    POST /security/grant                — grant a permission
    POST /security/revoke               — revoke a permission
    POST /security/elevate              — elevate agent to trust level
    POST /security/bootstrap/{agent_id} — apply zero-trust defaults
    POST /security/isolate/{agent_id}   — manually isolate an agent
    POST /security/release/{agent_id}   — release an isolated agent
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.security.capability_guard import get_guard
from core.security.permissions import TrustLevel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["security"])


# ── Request bodies ─────────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    agent_id:       str
    permission_id:  str
    granted_by:     str = "admin"
    expires_at:     Optional[str] = None

class RevokeRequest(BaseModel):
    agent_id:       str
    permission_id:  str
    revoked_by:     str = "admin"

class ElevateRequest(BaseModel):
    agent_id:       str
    level:          str           # e.g. "STANDARD"
    granted_by:     str = "admin"

class IsolateRequest(BaseModel):
    reason:     str
    isolated_by: str = "admin"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status")
def security_status():
    """[SECURITY] System-wide security stats summary."""
    try:
        return JSONResponse({"ok": True, "stats": get_guard().get_stats()})
    except Exception as exc:
        logger.error("[SECURITY] /security/status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/permissions")
def security_permissions(
    agent_id: Optional[str] = Query(None, description="Agent ID to inspect. Omit for catalog."),
):
    """[SECURITY] List active permissions for an agent, or the full catalog."""
    try:
        guard = get_guard()
        if agent_id:
            perms = guard.get_permissions(agent_id)
            return JSONResponse({
                "ok": True,
                "agent_id":   agent_id,
                "count":      len(perms),
                "permissions": perms,
                "isolated":   guard.is_isolated(agent_id),
            })
        return JSONResponse({
            "ok": True,
            "catalog": guard.get_catalog(),
            "count": len(guard.get_catalog()),
        })
    except Exception as exc:
        logger.error("[SECURITY] /security/permissions error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/events")
def security_events(
    agent_id:  Optional[str] = Query(None),
    severity:  Optional[str] = Query(None, description="INFO / WARNING / CRITICAL"),
    limit:     int           = Query(100, le=500),
):
    """[SECURITY] Security event log, newest first."""
    try:
        events = get_guard().list_security_events(agent_id=agent_id, severity=severity, limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        logger.error("[SECURITY] /security/events error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/violations")
def security_violations(
    agent_id: Optional[str]  = Query(None),
    resolved: Optional[bool] = Query(None),
    limit:    int             = Query(100, le=500),
):
    """[SECURITY] Policy violations log."""
    try:
        violations = get_guard().list_violations(agent_id=agent_id, resolved=resolved, limit=limit)
        return JSONResponse({"ok": True, "count": len(violations), "violations": violations})
    except Exception as exc:
        logger.error("[SECURITY] /security/violations error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/isolated")
def security_isolated():
    """[SECURITY] List all currently isolated agents."""
    try:
        agents = get_guard().list_isolated_agents()
        return JSONResponse({"ok": True, "count": len(agents), "isolated_agents": agents})
    except Exception as exc:
        logger.error("[SECURITY] /security/isolated error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/logs")
def security_logs(
    agent_id: Optional[str] = Query(None),
    action:   Optional[str] = Query(None, description="GRANT / REVOKE / CHECK_PASS / CHECK_FAIL"),
    limit:    int            = Query(200, le=1000),
):
    """[SECURITY] Permission audit log."""
    try:
        logs = get_guard().list_permission_logs(agent_id=agent_id, action=action, limit=limit)
        return JSONResponse({"ok": True, "count": len(logs), "logs": logs})
    except Exception as exc:
        logger.error("[SECURITY] /security/logs error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/catalog")
def security_catalog():
    """[SECURITY] Full permission catalog."""
    try:
        catalog = get_guard().get_catalog()
        return JSONResponse({"ok": True, "count": len(catalog), "catalog": catalog})
    except Exception as exc:
        logger.error("[SECURITY] /security/catalog error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/threat/{agent_id}")
def security_threat(agent_id: str):
    """[SECURITY] Threat level assessment for a single agent."""
    try:
        threat = get_guard().get_threat_level(agent_id)
        return JSONResponse({"ok": True, "threat": threat})
    except Exception as exc:
        logger.error("[SECURITY] /security/threat/%s error: %s", agent_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Write endpoints ────────────────────────────────────────────────────────────

@router.post("/grant")
def security_grant(body: GrantRequest):
    """[PERMISSION] Grant a permission to an agent."""
    try:
        ok = get_guard().grant(
            body.agent_id, body.permission_id,
            granted_by=body.granted_by,
            expires_at=body.expires_at,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"Unknown permission '{body.permission_id}'")
        return JSONResponse({"ok": True, "granted": body.permission_id, "agent_id": body.agent_id})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/revoke")
def security_revoke(body: RevokeRequest):
    """[PERMISSION] Revoke a permission from an agent."""
    try:
        ok = get_guard().revoke(body.agent_id, body.permission_id, revoked_by=body.revoked_by)
        return JSONResponse({"ok": ok, "revoked": body.permission_id, "agent_id": body.agent_id})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/elevate")
def security_elevate(body: ElevateRequest):
    """[PERMISSION] Elevate an agent to a trust level."""
    try:
        level = TrustLevel.from_string(body.level)
        perms = get_guard().elevate(body.agent_id, level, granted_by=body.granted_by)
        return JSONResponse({
            "ok": True,
            "agent_id": body.agent_id,
            "level": level.name,
            "granted_permissions": perms,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/bootstrap/{agent_id}")
def security_bootstrap(agent_id: str):
    """[PERMISSION] Apply zero-trust defaults to an agent."""
    try:
        perms = get_guard().bootstrap_new_agent(agent_id)
        return JSONResponse({"ok": True, "agent_id": agent_id, "bootstrapped_permissions": perms})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/isolate/{agent_id}")
def security_isolate(agent_id: str, body: IsolateRequest):
    """[SECURITY] Manually isolate an agent."""
    try:
        get_guard().isolate(agent_id, reason=body.reason, by=body.isolated_by)
        return JSONResponse({"ok": True, "agent_id": agent_id, "isolated": True})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/release/{agent_id}")
def security_release(agent_id: str):
    """[SECURITY] Release an isolated agent."""
    try:
        ok = get_guard().release(agent_id)
        return JSONResponse({"ok": ok, "agent_id": agent_id, "released": ok})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
