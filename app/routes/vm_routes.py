# app/routes/vm_routes.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.isolation_abstraction.unified_isolation_runtime import get_unified_runtime
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionPayload, ExecutionContext,
)
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy, IsolationUnavailableError,
)

router = APIRouter(prefix="/vm", tags=["vm-isolation"])


class ExecuteRequest(BaseModel):
    command: Optional[str] = None
    code: Optional[str] = None
    timeout_seconds: int = 30
    policy: str = "best_available"
    required_tier: Optional[str] = None
    minimum_security_score: int = 0
    requires_forensics: bool = False
    requires_network_isolation: bool = False
    correlation_id: Optional[str] = None
    preserve_forensics: bool = False


@router.get("/status")
def vm_status():
    """Host capability map and available tiers."""
    snap = get_unified_runtime()._detector.detect()
    return {
        "host_os": snap.host_os,
        "available_tiers": [t.name for t in sorted(snap.available_tiers)],
        "docker_runtime": snap.docker_runtime,
        "virtualization_type": snap.virtualization_type,
        "cache_health_score": snap.cache_health_score,
        "detected_at": snap.detected_at.isoformat(),
    }


@router.get("/capabilities")
def vm_capabilities():
    """Full capability snapshot."""
    snap = get_unified_runtime()._detector.detect()
    return {
        "has_firecracker": snap.has_firecracker,
        "has_qemu": snap.has_qemu,
        "has_kvm": snap.has_kvm,
        "has_docker": snap.has_docker,
        "has_wsl2": snap.has_wsl2,
        "host_os": snap.host_os,
        "docker_runtime": snap.docker_runtime,
        "virtualization_type": snap.virtualization_type,
        "available_tiers": [t.name for t in sorted(snap.available_tiers)],
        "cache_source": snap.cache_source,
        "cache_generation": snap.cache_generation,
        "cache_health_score": snap.cache_health_score,
        "detected_at": snap.detected_at.isoformat(),
    }


@router.post("/capabilities/refresh")
def vm_capabilities_refresh():
    """Rate-limited capability re-probe."""
    try:
        snap = get_unified_runtime().refresh_capabilities(reason="api_request")
        return {
            "available_tiers": [t.name for t in sorted(snap.available_tiers)],
            "detected_at": snap.detected_at.isoformat(),
            "cache_generation": snap.cache_generation,
        }
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))


@router.post("/execute")
async def vm_execute(req: ExecuteRequest):
    """Execute a command in an isolated runtime."""
    try:
        policy = IsolationPolicy(req.policy)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown policy: {req.policy}")

    required_tier: Optional[IsolationTier] = None
    if req.required_tier:
        try:
            required_tier = IsolationTier[req.required_tier.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {req.required_tier}")

    ctx = ExecutionContext(
        correlation_id=req.correlation_id,
        preserve_forensics=req.preserve_forensics,
    )
    payload = ExecutionPayload(
        command=req.command,
        code=req.code,
        timeout_seconds=req.timeout_seconds,
    )
    try:
        result = await get_unified_runtime().execute_isolated(
            payload=payload,
            policy=policy,
            ctx=ctx,
            required_tier=required_tier,
            minimum_security_score=req.minimum_security_score,
            requires_forensics=req.requires_forensics,
            requires_network_isolation=req.requires_network_isolation,
        )
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "tier_used": result.tier_used.name,
            "duration_ms": result.duration_ms,
            "execution_id": result.execution_id,
            "correlation_id": result.correlation_id,
            "security_score": result.negotiation.security_score if result.negotiation else None,
            "fallback_level": result.negotiation.fallback_level if result.negotiation else 0,
        }
    except IsolationUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/negotiation/history")
def vm_negotiation_history(limit: int = 50):
    """Recent negotiation decisions with full reasoning trail."""
    return get_unified_runtime().get_negotiation_history(limit=limit)


@router.get("/list")
def vm_list():
    """Active and recent VMs."""
    import sqlite3
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT vm_id, session_id, tier, status, security_score, "
                "risk_adjusted_score, fallback_level, agent_id, created_at "
                "FROM virtual_machines ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [
            {
                "vm_id": r[0], "session_id": r[1], "tier": r[2],
                "status": r[3], "security_score": r[4],
                "risk_adjusted_score": r[5], "fallback_level": r[6],
                "agent_id": r[7], "created_at": r[8],
            }
            for r in rows
        ]
    except Exception:
        return []


@router.get("/threats")
def vm_threats(limit: int = 50):
    """Recent escape attempts and anomalies."""
    import sqlite3
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT attempt_id, vm_id, signal_type, severity, "
                "response_action, timestamp "
                "FROM vm_escape_attempts ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "attempt_id": r[0], "vm_id": r[1], "signal_type": r[2],
                "severity": r[3], "response_action": r[4], "timestamp": r[5],
            }
            for r in rows
        ]
    except Exception:
        return []


@router.get("/policies")
def vm_policies():
    """Current (non-superseded) VM policies."""
    import sqlite3, json
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT profile, definition, minimum_security_score, version "
                "FROM vm_policies WHERE superseded_at IS NULL"
            ).fetchall()
        return [
            {
                "profile": r[0],
                "definition": json.loads(r[1]) if r[1] else {},
                "minimum_security_score": r[2],
                "version": r[3],
            }
            for r in rows
        ]
    except Exception:
        return []
