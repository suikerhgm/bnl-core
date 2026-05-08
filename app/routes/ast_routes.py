"""
AST Security API routes — /ast/*

POST /ast/analyze           — scan code string
POST /ast/analyze_file      — scan a file path (relative to project root)
GET  /ast/reports           — list scan summaries
GET  /ast/reports/{scan_id} — full scan detail
GET  /ast/threats           — list all detected threat patterns
GET  /ast/quarantine        — quarantine decisions (optionally blocked-only)
GET  /ast/forensics/{id}    — full forensic report for a scan
GET  /ast/status            — engine stats
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.ast_security.ast_security_engine import get_ast_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ast", tags=["ast_security"])


class AnalyzeRequest(BaseModel):
    source:    str
    filename:  str = "<code>"
    agent_id:  Optional[str] = None

class AnalyzeFileRequest(BaseModel):
    path:      str
    agent_id:  Optional[str] = None


@router.post("/analyze")
async def ast_analyze(body: AnalyzeRequest):
    """[AST] Scan a Python source code string for security threats."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_ast_engine().scan(
                body.source,
                filename=body.filename,
                agent_id=body.agent_id,
            ),
        )
        return JSONResponse({
            "ok":       True,
            "blocked":  result.blocked,
            "safe":     result.safe,
            **result.to_dict(),
        })
    except Exception as exc:
        logger.error("[AST] /ast/analyze error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/analyze_file")
async def ast_analyze_file(body: AnalyzeFileRequest):
    """[AST] Scan a file (relative to project root) for security threats."""
    import asyncio
    try:
        p = Path(body.path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {body.path}")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_ast_engine().scan_file(p, agent_id=body.agent_id),
        )
        return JSONResponse({
            "ok": True, "blocked": result.blocked,
            **result.to_dict(),
        })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
def ast_status():
    """[AST] Engine statistics."""
    try:
        return JSONResponse({"ok": True, "stats": get_ast_engine().get_stats()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/reports")
def ast_reports(
    risk_level: Optional[str] = Query(None),
    agent_id:   Optional[str] = Query(None),
    limit:      int           = Query(50, le=200),
):
    """[AST] List scan summaries."""
    try:
        scans = get_ast_engine().list_scans(
            risk_level=risk_level, agent_id=agent_id, limit=limit
        )
        return JSONResponse({"ok": True, "count": len(scans), "scans": scans})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/reports/{scan_id}")
def ast_report_detail(scan_id: str):
    """[AST] Full scan detail including all findings."""
    try:
        data = get_ast_engine().get_scan(scan_id)
        if not data:
            raise HTTPException(status_code=404, detail="Scan not found")
        return JSONResponse({"ok": True, "scan": data})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/threats")
def ast_threats(limit: int = Query(100, le=500)):
    """[AST] List all detected threat patterns across scans."""
    try:
        threats = get_ast_engine().list_threats(limit=limit)
        return JSONResponse({"ok": True, "count": len(threats), "threats": threats})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/quarantine")
def ast_quarantine(blocked_only: bool = Query(False)):
    """[AST] List quarantine decisions."""
    try:
        decisions = get_ast_engine().list_quarantine_decisions(blocked_only=blocked_only)
        return JSONResponse({"ok": True, "count": len(decisions), "decisions": decisions})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/forensics/{scan_id}")
def ast_forensics(scan_id: str):
    """[AST] Full forensic report for a high-risk scan."""
    try:
        report = get_ast_engine().get_forensic_report(scan_id)
        if not report:
            raise HTTPException(status_code=404, detail="Forensic report not found")
        return JSONResponse({"ok": True, "report": report})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
