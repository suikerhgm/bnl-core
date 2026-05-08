"""
Recovery API routes — /recovery/*

Endpoints:
    GET  /recovery/status                   — system-wide recovery stats + chain integrity
    GET  /recovery/snapshots                — list snapshots (filterable)
    GET  /recovery/snapshots/{id}           — single snapshot detail
    GET  /recovery/snapshots/{id}/manifest  — snapshot manifest (file hashes)
    GET  /recovery/restore_events           — restore event history
    GET  /recovery/rollback_events          — rollback event history
    GET  /recovery/audit                    — immutable audit trail tail
    GET  /recovery/forensics                — forensic events log
    GET  /recovery/guardian                 — guardian health status
    GET  /recovery/integrity                — live system integrity check
    POST /recovery/create                   — create a new snapshot
    POST /recovery/restore/{snapshot_id}    — restore a specific snapshot
    POST /recovery/emergency_restore        — EMERGENCY full restore (big red button)
    POST /recovery/checkpoint/{snapshot_id} — promote to SAFE checkpoint
    POST /recovery/rollback                 — manual rollback trigger
    POST /recovery/validate/{snapshot_id}   — re-validate a snapshot
    POST /recovery/start_guardian           — start the recovery guardian daemon
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.recovery.immutable_audit_log import get_audit_log
from core.recovery.snapshot_manager import get_snapshot_manager
from core.recovery.restore_manager import get_restore_manager
from core.recovery.rollback_engine import get_rollback_engine
from core.recovery.recovery_guardian import get_recovery_guardian
from core.recovery.safe_checkpoint import SafeCheckpoint
from core.recovery.integrity_validator import IntegrityValidator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recovery", tags=["recovery"])


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateSnapshotRequest(BaseModel):
    label:       str = ""
    created_by:  str = "api"
    notes:       str = ""

class RestoreRequest(BaseModel):
    restore_type: str = "SAFE_RESTORE"
    triggered_by: str = "api"

class EmergencyRestoreRequest(BaseModel):
    triggered_by: str = "emergency_button"
    confirm:      bool = False

class CheckpointRequest(BaseModel):
    level:      str = "SAFE"
    granted_by: str = "admin"

class RollbackRequest(BaseModel):
    reason: str
    trigger: str = "manual"

class PartialRestoreRequest(BaseModel):
    snapshot_id: str
    subsystem:   str   # registry | permissions | runtime


# ── Read endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
def recovery_status():
    """[RECOVERY] System-wide recovery statistics and audit chain integrity."""
    try:
        stats = get_audit_log().get_stats()
        snap_stats = get_snapshot_manager().get_stats()
        guardian   = get_recovery_guardian().get_health()
        return JSONResponse({
            "ok": True,
            "stats":     {**stats, **snap_stats},
            "guardian":  guardian,
        })
    except Exception as exc:
        logger.error("[RECOVERY] /recovery/status: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/snapshots")
def recovery_snapshots(
    status:           Optional[str] = Query(None),
    checkpoint_level: Optional[str] = Query(None),
    limit:            int           = Query(50, le=200),
):
    """[RECOVERY] List snapshots with optional filters."""
    try:
        snaps = get_snapshot_manager().list_snapshots(
            status=status, checkpoint_level=checkpoint_level, limit=limit
        )
        return JSONResponse({"ok": True, "count": len(snaps), "snapshots": snaps})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/snapshots/{snapshot_id}/manifest")
def recovery_manifest(snapshot_id: str):
    """[RECOVERY] Retrieve the manifest (file hashes) of a snapshot."""
    try:
        manifest = get_snapshot_manager().get_manifest(snapshot_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="Manifest not found")
        return JSONResponse({"ok": True, "manifest": manifest})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/snapshots/{snapshot_id}")
def recovery_snapshot_detail(snapshot_id: str):
    """[RECOVERY] Single snapshot detail."""
    try:
        snap = get_snapshot_manager().get_snapshot(snapshot_id)
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return JSONResponse({"ok": True, "snapshot": snap})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/restore_events")
def recovery_restore_events(limit: int = Query(50, le=200)):
    """[RECOVERY] Restore event history."""
    try:
        events = get_restore_manager().get_restore_events(limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rollback_events")
def recovery_rollback_events(limit: int = Query(50, le=200)):
    """[RECOVERY] Rollback event history."""
    try:
        events = get_restore_manager().get_rollback_events(limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/audit")
def recovery_audit(limit: int = Query(100, le=500)):
    """[RECOVERY] Immutable audit trail (newest first)."""
    try:
        entries = get_audit_log().get_audit_tail(limit=limit)
        chain_ok, broken_at = get_audit_log().verify_chain()
        return JSONResponse({
            "ok": True,
            "chain_intact": chain_ok,
            "broken_at_seq": broken_at,
            "count": len(entries),
            "entries": entries,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/forensics")
def recovery_forensics(limit: int = Query(50, le=200)):
    """[RECOVERY] Forensic events log."""
    try:
        events = get_audit_log().list_forensic_events(limit=limit)
        return JSONResponse({"ok": True, "count": len(events), "events": events})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/guardian")
def recovery_guardian_status():
    """[RECOVERY] RecoveryGuardian daemon health status."""
    try:
        return JSONResponse({"ok": True, **get_recovery_guardian().get_health()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/integrity")
def recovery_integrity():
    """[RECOVERY] Live system integrity check (DBs + critical files)."""
    try:
        v = IntegrityValidator()
        return JSONResponse({
            "ok": True,
            "databases":      v.check_all_dbs(),
            "critical_files": v.check_critical_files(),
            "chain":          {"intact": get_audit_log().verify_chain()[0]},
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Write endpoints ────────────────────────────────────────────────────────────

@router.post("/create")
async def recovery_create(body: CreateSnapshotRequest):
    """[RECOVERY] Create a new snapshot of all critical system state."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        snap = await loop.run_in_executor(
            None,
            lambda: get_snapshot_manager().create_snapshot(
                label=body.label,
                created_by=body.created_by,
                notes=body.notes,
            ),
        )
        return JSONResponse({"ok": True, "snapshot": snap})
    except Exception as exc:
        logger.error("[RECOVERY] /recovery/create: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/restore/{snapshot_id}")
async def recovery_restore(snapshot_id: str, body: RestoreRequest):
    """[RECOVERY] Restore a specific snapshot."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_restore_manager().restore_snapshot(
                snapshot_id,
                restore_type=body.restore_type,
                triggered_by=body.triggered_by,
            ),
        )
        return JSONResponse({"ok": result.get("success", False), **result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/emergency_restore")
async def recovery_emergency(body: EmergencyRestoreRequest):
    """[EMERGENCY] Trigger full emergency restore from last SAFE checkpoint."""
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Emergency restore requires confirm=true in request body",
        )
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_restore_manager().emergency_restore(
                triggered_by=body.triggered_by,
            ),
        )
        return JSONResponse({"ok": result.get("success", False), **result})
    except Exception as exc:
        logger.error("[RECOVERY] /recovery/emergency_restore: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/checkpoint/{snapshot_id}")
def recovery_checkpoint(snapshot_id: str, body: CheckpointRequest):
    """[RECOVERY] Promote a snapshot to SAFE / STABLE / TRUSTED checkpoint."""
    try:
        cp = SafeCheckpoint()
        level = body.level.upper()
        if level == "SAFE":
            ok, msg = cp.promote_to_safe(snapshot_id)
        elif level == "STABLE":
            ok, msg = cp.promote_to_stable(snapshot_id)
        elif level == "TRUSTED":
            ok, msg = cp.promote_to_trusted(snapshot_id, body.granted_by)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown level: {level}")
        return JSONResponse({"ok": ok, "message": msg, "level": level})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/rollback")
def recovery_rollback(body: RollbackRequest):
    """[RECOVERY] Manual rollback to last SAFE snapshot."""
    try:
        result = get_rollback_engine().trigger_rollback(body.trigger, body.reason)
        return JSONResponse({"ok": result.get("success", False), **result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/validate/{snapshot_id}")
def recovery_validate(snapshot_id: str):
    """[RECOVERY] Re-validate snapshot integrity."""
    try:
        report = get_snapshot_manager().validate_snapshot(snapshot_id)
        return JSONResponse({"ok": report.passed(), "report": report.to_dict()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/partial_restore")
async def recovery_partial(body: PartialRestoreRequest):
    """[RECOVERY] Partial restore of a specific subsystem (registry/permissions/runtime)."""
    import asyncio
    try:
        rm = get_restore_manager()
        loop = asyncio.get_event_loop()
        subsystem = body.subsystem.lower()
        if subsystem == "registry":
            result = await loop.run_in_executor(None, lambda: rm.restore_registry(body.snapshot_id))
        elif subsystem == "permissions":
            result = await loop.run_in_executor(None, lambda: rm.restore_permissions(body.snapshot_id))
        elif subsystem == "runtime":
            result = await loop.run_in_executor(None, lambda: rm.restore_runtime_state(body.snapshot_id))
        else:
            raise HTTPException(status_code=400, detail=f"Unknown subsystem: {subsystem}")
        return JSONResponse({"ok": result.get("success", False), **result})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/start_guardian")
def recovery_start_guardian():
    """[RECOVERY] Start the RecoveryGuardian background daemon."""
    try:
        get_recovery_guardian().start()
        return JSONResponse({"ok": True, "guardian": "started"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
