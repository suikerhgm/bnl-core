"""
Nexus BNL — Project Dashboard
==============================
Read-only web UI for browsing generated projects.

Run:
    uvicorn app.dashboard:app --reload --port 8080
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app.config import API_KEY
from app.dependencies import verify_api_key
from app.routes.agent_routes import router as agents_router
from app.routes.security_routes import router as security_router
from app.routes.sandbox_routes import router as sandbox_router
from app.routes.isolation_routes import router as isolation_router
from app.routes.recovery_routes import router as recovery_router
from app.routes.ast_routes import router as ast_router
from core.runtime.process_manager import get_manager
from core.actions.command_action import CommandAction, get_run_command
from core.runtime.port_allocator import find_free_port

logger = logging.getLogger(__name__)

BASE_DIR = Path("generated_apps").resolve()

app = FastAPI(title="Nexus BNL Dashboard", docs_url=None, redoc_url=None)

# Agent registry API — available at /agents/*
app.include_router(agents_router)
app.include_router(security_router)
app.include_router(sandbox_router)
app.include_router(isolation_router)
app.include_router(recovery_router)
app.include_router(ast_router)


# ── Models ─────────────────────────────────────────────────────────────────

class ProjectSummary(BaseModel):
    id: str
    path: str
    file_count: int


class FileInfo(BaseModel):
    path: str
    agent: Optional[str] = None


class ProjectDetail(BaseModel):
    id: str
    path: str
    files: List[FileInfo]


# ── Helpers ────────────────────────────────────────────────────────────────

def _list_projects() -> List[ProjectSummary]:
    if not BASE_DIR.exists():
        return []
    projects = []
    for entry in sorted(BASE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        files = [
            str(f.relative_to(entry))
            for f in entry.rglob("*")
            if f.is_file() and f.name != "_nexus_metadata.json"
        ]
        projects.append(ProjectSummary(
            id=entry.name,
            path=str(entry),
            file_count=len(files),
        ))
    return projects


def _resolve_safe(project_id: str, rel_path: str | None = None) -> Path:
    """Resolve a project dir (and optionally a file inside it) with path-traversal protection."""
    safe_id = Path(project_id).name  # strip any directory component
    project_path = (BASE_DIR / safe_id).resolve()

    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if rel_path is None:
        return project_path

    # Reject absolute paths up-front
    if Path(rel_path).is_absolute():
        raise HTTPException(status_code=400, detail="Absolute paths are not allowed")

    candidate = (project_path / rel_path).resolve()
    try:
        candidate.relative_to(project_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal detected")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"File '{rel_path}' not found")

    return candidate


# ── API endpoints ──────────────────────────────────────────────────────────

@app.get("/status")
def system_status():
    """List all apps in generated_apps/ merged with live process state."""
    manager = get_manager()
    manager.sync_from_db()
    proc_index = {p["project_id"]: p for p in manager.list_all()}

    apps = []
    if BASE_DIR.exists():
        for entry in sorted(BASE_DIR.iterdir()):
            if not entry.is_dir():
                continue
            pr = proc_index.get(entry.name, {})
            proc_obj = manager.get_raw(entry.name)
            pid = None
            if proc_obj and proc_obj.get("process") is not None:
                pid = proc_obj["process"].pid
            apps.append({
                "name":   entry.name,
                "status": pr.get("status", "stopped"),
                "port":   pr.get("port"),
                "pid":    pid,
            })

    return JSONResponse({"apps": apps})


# ── Process control endpoints ──────────────────────────────────────────────

@app.post("/process/stop_all", dependencies=[Depends(verify_api_key)])
async def stop_all_processes():
    """Terminate every registered running process."""
    count = get_manager().stop_all()
    return JSONResponse({"ok": True, "stopped": count})


@app.get("/process/history", dependencies=[Depends(verify_api_key)])
async def process_history():
    """Return all completed process executions, newest first."""
    return JSONResponse(get_manager().get_history())


@app.get("/process", dependencies=[Depends(verify_api_key)])
async def list_processes():
    """Return a summary of every registered process, synced from DB."""
    get_manager().sync_from_db()
    return JSONResponse(get_manager().list_all())


@app.get("/process/stream/{project_id}")
async def stream_logs(project_id: str, request: Request):
    """Server-Sent Events stream of live log lines for a project.

    Auth: cookie 'nexus_api_key' (set by JS before opening EventSource).
    Resume: honours the standard Last-Event-ID header sent by the browser
            on reconnect — no log lines are replayed or skipped.
    """
    # ── Cookie auth (no key in URL / server logs) ────────────────────
    api_key = request.cookies.get("nexus_api_key")
    if not api_key or api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key inválida")

    # ── Resume support via Last-Event-ID ─────────────────────────────
    raw_last_id = request.headers.get("last-event-id")
    initial_index = int(raw_last_id) + 1 if raw_last_id and raw_last_id.isdigit() else 0

    manager = get_manager()
    manager.sync_from_db()   # ensure we see processes started by the backend

    async def event_generator():
        last_index  = initial_index
        file_offset = 0   # byte offset into .nexus.log for remote processes
        try:
            while True:
                try:
                    # Re-sync so status/port updates from the backend are visible
                    manager.sync_from_db()
                    data = manager.get(project_id)

                    if data is None:
                        logger.debug("stream '%s': process not registered yet", project_id)
                        yield "event: status\ndata: {\"status\": \"stopped\", \"port\": null}\n\n"
                        await asyncio.sleep(1.0)
                        continue

                    had_new  = False
                    status   = data.get("status", "unknown")
                    port     = data.get("port")
                    is_local = data.get("is_local", False)

                    if is_local:
                        # This instance owns the process — stream from in-memory deque
                        logs     = data.get("logs") or []
                        new_logs = logs[last_index:]
                        had_new  = bool(new_logs)
                        for i, line in enumerate(new_logs, start=last_index):
                            safe = line.replace("\n", " ").replace("\r", "")
                            yield f"id: {i}\ndata: {safe}\n\n"
                        last_index += len(new_logs)
                    else:
                        # Remote process (launched by backend) — tail .nexus.log
                        cwd = data.get("cwd") or ""
                        if not cwd:
                            logger.debug("stream '%s': is_local=False but cwd missing", project_id)
                        else:
                            log_path = Path(cwd) / ".nexus.log"
                            if log_path.exists():
                                try:
                                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                                        f.seek(file_offset)
                                        chunk = f.read()
                                        if chunk:
                                            had_new = True
                                            file_offset += len(chunk.encode("utf-8", errors="replace"))
                                            for raw_line in chunk.splitlines():
                                                if raw_line:
                                                    safe = raw_line.replace("\n", " ").replace("\r", "")
                                                    yield f"id: {last_index}\ndata: {safe}\n\n"
                                                    last_index += 1
                                except OSError as exc:
                                    logger.debug("stream '%s': log read error: %s", project_id, exc)

                    # Status event on every tick
                    yield (
                        f"event: status\n"
                        f"data: {json.dumps({'status': status, 'port': port})}\n\n"
                    )

                    if status in ("stopped", "failed"):
                        yield "event: end\ndata: process ended\n\n"
                        break

                    if not had_new:
                        await asyncio.sleep(0.3)

                except (GeneratorExit, asyncio.CancelledError):
                    raise   # let outer handler catch these
                except Exception as exc:
                    logger.warning("stream '%s': tick error (continuing): %s", project_id, exc)
                    await asyncio.sleep(1.0)

        except (GeneratorExit, asyncio.CancelledError):
            pass  # client disconnected — normal shutdown

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/process/{project_id}", dependencies=[Depends(verify_api_key)])
async def get_process(project_id: str):
    """Return live status, logs, port, retry count, and latest snapshot for a project."""
    manager = get_manager()
    manager.sync_from_db()
    data = manager.get(project_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No process registered for '{project_id}'")
    # For remote processes supplement in-memory logs with the .nexus.log file.
    logs = list(data["logs"])
    if not logs and data.get("cwd"):
        log_path = Path(data["cwd"]) / ".nexus.log"
        if log_path.exists():
            try:
                logs = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            except OSError:
                pass

    # Retry count from RepairEngine (0 if no repair attempted yet)
    retry_count = 0
    try:
        from core.repair_engine import get_repair_engine
        retry_count = get_repair_engine().get_retry_count(project_id)
    except Exception:
        pass

    # Latest snapshot timestamp
    latest_snap = None
    try:
        from core.snapshot_manager import latest_snapshot_timestamp
        latest_snap = latest_snapshot_timestamp(project_id)
    except Exception:
        pass

    # Derive a simple health label
    raw_status = data.get("status", "unknown")
    health = (
        "healthy" if raw_status == "running"
        else "crashed" if raw_status == "failed"
        else raw_status
    )

    return JSONResponse({
        "status":           raw_status,
        "health":           health,
        "logs":             logs,
        "port":             data.get("port"),
        "pid":              data.get("pid"),
        "command":          data.get("command"),
        "is_local":         data.get("is_local", False),
        "retry_count":      retry_count,
        "latest_snapshot":  latest_snap,
    })


@app.get("/snapshots/{project_id}", dependencies=[Depends(verify_api_key)])
async def get_snapshots(project_id: str):
    """Return the list of snapshots for a project (newest first)."""
    from core.snapshot_manager import list_snapshots, latest_snapshot_timestamp
    snaps = list_snapshots(project_id)
    return JSONResponse({
        "project_id": project_id,
        "snapshots":  snaps,
        "latest":     latest_snapshot_timestamp(project_id),
        "count":      len(snaps),
    })


@app.post("/snapshots/{project_id}/restore", dependencies=[Depends(verify_api_key)])
async def restore_project_snapshot(project_id: str):
    """Restore the latest snapshot for a project."""
    project_path = BASE_DIR / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    from core.snapshot_manager import restore_snapshot
    ok = restore_snapshot(project_id, project_path)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No snapshot found for '{project_id}'")
    return JSONResponse({"restored": True, "project_id": project_id})


@app.post("/process/{project_id}/stop", dependencies=[Depends(verify_api_key)])
async def stop_process(project_id: str):
    """Terminate a running process."""
    manager = get_manager()
    if manager.get(project_id) is None:
        raise HTTPException(status_code=404, detail=f"No process registered for '{project_id}'")
    manager.stop(project_id)
    return JSONResponse({"ok": True, "project_id": project_id})


@app.post("/process/{project_id}/restart", dependencies=[Depends(verify_api_key)])
async def restart_process(project_id: str):
    """Stop the current process and re-launch it with the same command."""
    manager = get_manager()
    entry = manager.get_raw(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No process registered for '{project_id}'")

    command = entry.get("command")   # List[str] stored by ProcessManager
    cwd = entry.get("cwd", "")
    if not command or not isinstance(command, list) or not cwd:
        raise HTTPException(status_code=400, detail="Cannot restart: missing command or cwd")

    manager.stop(project_id)
    await asyncio.sleep(0.5)  # give OS time to reap the child

    cmd_action = CommandAction({
        "operation": "run",
        "params": {"command": command, "cwd": cwd, "project_id": project_id},
    })
    result = await cmd_action.execute()
    if result.get("success"):
        return JSONResponse({"ok": True, "project_id": project_id, "pid": result["result"].get("pid")})
    raise HTTPException(status_code=500, detail=result.get("error", "Restart failed"))


@app.post("/process/{project_id}/start", dependencies=[Depends(verify_api_key)])
async def start_process(project_id: str):
    """
    Launch a project that is stopped or has never been registered.

    Strategy:
    1. If already registered with a stored command → re-use it (same as restart).
    2. If not registered → scan generated_projects/{project_id}/ for a known
       entry-point (backend.py / main.py / app.py / package.json) and build
       the uvicorn/npm command dynamically.
    """
    manager = get_manager()
    entry = manager.get_raw(project_id)

    command: Optional[List[str]] = None
    cwd: Optional[str] = None

    if entry and entry.get("command") and entry.get("cwd"):
        # Re-use stored command from previous run
        command = entry["command"]
        cwd = entry["cwd"]
    else:
        # Detect entry-point from disk
        project_path = BASE_DIR / project_id
        if not project_path.is_dir():
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found on disk")

        file_names = [f.name for f in project_path.rglob("*") if f.is_file()]
        fake_files = [{"path": n} for n in file_names]
        port = find_free_port()
        command = get_run_command(str(project_path), fake_files, port=port)
        cwd = str(project_path)

        if not command:
            raise HTTPException(
                status_code=422,
                detail="No recognisable entry-point found (backend.py / main.py / app.py / package.json)",
            )

    if entry and entry.get("status") == "running":
        manager.stop(project_id)
        await asyncio.sleep(0.4)

    cmd_action = CommandAction({
        "operation": "run",
        "params": {"command": command, "cwd": cwd, "project_id": project_id},
    })
    result = await cmd_action.execute()
    if result.get("success"):
        return JSONResponse({
            "ok": True,
            "project_id": project_id,
            "pid": result["result"].get("pid"),
            "command": command,
        })
    raise HTTPException(status_code=500, detail=result.get("error", "Start failed"))


@app.get("/projects", response_model=List[ProjectSummary], dependencies=[Depends(verify_api_key)])
def list_projects():
    """List all generated projects with name, path, and file count."""
    return _list_projects()


@app.get("/projects/{project_id}", response_model=ProjectDetail, dependencies=[Depends(verify_api_key)])
def project_detail(project_id: str):
    """Return all file paths inside a project, with agent metadata when available."""
    project_path = _resolve_safe(project_id)

    # Load agent metadata sidecar if present
    agent_map: dict = {}
    meta_file = project_path / "_nexus_metadata.json"
    if meta_file.exists():
        try:
            agent_map = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            pass  # metadata is optional — never block on parse failure

    file_paths = sorted(
        str(f.relative_to(project_path))
        for f in project_path.rglob("*")
        if f.is_file() and f.name != "_nexus_metadata.json"
    )
    def _infer_agent(p: str) -> str:
        return "🏗️ backend" if p.startswith("backend/") or p.startswith("backend\\") else "🧑‍🏭 frontend"

    files = [FileInfo(path=p, agent=agent_map.get(p) or _infer_agent(p)) for p in file_paths]
    return ProjectDetail(id=project_id, path=str(project_path), files=files)


@app.get("/projects/{project_id}/file", dependencies=[Depends(verify_api_key)])
def file_content(project_id: str, path: str = Query(..., description="Relative file path")):
    """Return the raw content of a file inside a project."""
    file_path = _resolve_safe(project_id, path)
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return PlainTextResponse(content)


# ── Single-page HTML UI ────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
    background: #0d0d0d; color: #c9d1d9;
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
    font-size: 13px;
  }

  /* Top bar */
  #topbar {
    background: #161616; border-bottom: 1px solid #2a2a2a;
    padding: 8px 16px; display: flex; align-items: center; gap: 10px;
    flex-shrink: 0;
  }
  #topbar .logo { color: #58a6ff; font-weight: 700; font-size: 14px; }
  #topbar .sep  { color: #333; }
  #topbar .sub  { color: #555; font-size: 11px; }
  #topbar .spacer { flex: 1; }
  #topbar #ts { color: #383838; font-size: 10px; }

  /* Layout */
  #layout { display: flex; flex: 1; overflow: hidden; }

  /* ── Sidebar ── */
  #sidebar {
    width: 230px; flex-shrink: 0;
    background: #111; border-right: 1px solid #1e1e1e;
    display: flex; flex-direction: column; overflow: hidden;
  }
  #sidebar-hdr {
    padding: 8px 12px; font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.07em; color: #555;
    border-bottom: 1px solid #1a1a1a;
    display: flex; justify-content: space-between; align-items: center;
  }
  #proj-count {
    background: #1e1e1e; border-radius: 10px;
    padding: 1px 7px; font-size: 10px; color: #666;
  }
  #project-list { flex: 1; overflow-y: auto; }

  .proj-item {
    padding: 9px 12px; cursor: pointer;
    border-bottom: 1px solid #171717; border-left: 2px solid transparent;
    transition: background 0.1s;
  }
  .proj-item:hover  { background: #181818; }
  .proj-item.active { background: #152030; border-left-color: #58a6ff; }

  .pj-name {
    font-size: 12px; color: #ddd;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .pj-meta {
    margin-top: 3px; font-size: 11px;
    display: flex; align-items: center; gap: 5px;
  }
  .sdot { font-size: 7px; line-height: 1; }
  .s-running { color: #3fb950; }
  .s-stopped { color: #444; }
  .s-failed  { color: #f85149; }
  .s-unknown { color: #555; }
  .port-tag { color: #58a6ff; font-size: 10px; }
  .files-tag { color: #3a3a3a; font-size: 10px; }

  /* ── Main panel ── */
  #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  /* Toolbar */
  #toolbar {
    background: #151515; border-bottom: 1px solid #222;
    padding: 8px 14px; display: flex; align-items: center; gap: 8px;
    flex-shrink: 0; min-height: 46px;
  }
  #proj-lbl { color: #555; font-size: 13px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #proj-lbl.sel { color: #ddd; }

  .cbtn {
    padding: 4px 12px; font-size: 11px; cursor: pointer;
    border-radius: 4px; border: 1px solid #333;
    background: #1e1e1e; color: #aaa;
    font-family: inherit; transition: all 0.1s; white-space: nowrap;
  }
  .cbtn:hover:not(:disabled) { background: #252525; border-color: #555; }
  .cbtn:disabled { opacity: 0.3; cursor: default; }
  .cbtn.start { border-color: #1a4a23; color: #3fb950; }
  .cbtn.start:hover:not(:disabled) { background: #0a1f10; }
  .cbtn.stop  { border-color: #4a1a1a; color: #f85149; }
  .cbtn.stop:hover:not(:disabled)  { background: #1e0c0c; }
  .cbtn.restart { border-color: #2a2a6a; color: #8b96f0; }
  .cbtn.restart:hover:not(:disabled) { background: #111230; }

  #open-btn {
    padding: 4px 12px; font-size: 11px;
    border-radius: 4px; border: 1px solid #1a3a6a;
    background: #0d1f3a; color: #58a6ff;
    text-decoration: none; white-space: nowrap;
    transition: all 0.1s; display: none;
    font-family: inherit;
  }
  #open-btn:hover { background: #112850; border-color: #2a5aaa; }

  /* Status bar */
  #statusbar {
    padding: 5px 14px; font-size: 10px; color: #555;
    border-bottom: 1px solid #191919;
    background: #0e0e0e; flex-shrink: 0;
    display: none; align-items: center; gap: 14px; height: 28px;
  }
  .sb-item { display: flex; align-items: center; gap: 4px; }
  #sb-sdot { font-size: 7px; }
  #sb-stext { font-weight: 600; font-size: 11px; }
  #sb-port, #sb-pid { color: #888; font-size: 11px; }

  /* Log area */
  #log-area {
    flex: 1; overflow-y: auto; padding: 10px 14px;
    font-size: 12px; line-height: 1.6; color: #777;
    white-space: pre-wrap; word-break: break-all;
    background: #0d0d0d;
  }
  #log-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; color: #2a2a2a; font-size: 12px;
  }
  .ll { display: block; padding: 0 2px; }
  .ll:hover { background: rgba(255,255,255,0.02); }
  .ll-err  { color: #f85149; }
  .ll-warn { color: #e3b341; }
  .ll-info { color: #6ea87a; }
  .ll-sys  { color: #333; font-style: italic; }

  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: #0d0d0d; }
  ::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 2px; }
  ::-webkit-scrollbar-thumb:hover { background: #3a3a3a; }
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">⚙ Nexus</span>
  <span class="sep">|</span>
  <span class="sub">App Dashboard</span>
  <span class="spacer"></span>
  <span id="ts"></span>
</div>

<div id="layout">

  <!-- Sidebar -->
  <div id="sidebar">
    <div id="sidebar-hdr">
      <span>Projects</span>
      <span id="proj-count">0</span>
    </div>
    <div id="project-list">
      <div style="padding:12px;color:#333;font-size:11px">Loading…</div>
    </div>
  </div>

  <!-- Main panel -->
  <div id="main">

    <!-- Toolbar -->
    <div id="toolbar">
      <span id="proj-lbl">&#x2190; select a project</span>
      <button class="cbtn start"   id="btn-start"   disabled onclick="doStart()">&#x25B6; Start</button>
      <button class="cbtn stop"    id="btn-stop"    disabled onclick="doStop()">&#x25A0; Stop</button>
      <button class="cbtn restart" id="btn-restart" disabled onclick="doRestart()">&#x21BA; Restart</button>
      <a id="open-btn" target="_blank">&#x1F517; Open</a>
    </div>

    <!-- Status bar -->
    <div id="statusbar">
      <div class="sb-item">
        <span id="sb-sdot" class="sdot s-stopped">&#x25CF;</span>
        <span id="sb-stext" class="s-stopped">stopped</span>
      </div>
      <div class="sb-item" id="sb-port-row" style="display:none">
        <span style="color:#3a3a3a">port</span>
        <span id="sb-port"></span>
      </div>
      <div class="sb-item" id="sb-pid-row" style="display:none">
        <span style="color:#3a3a3a">pid</span>
        <span id="sb-pid"></span>
      </div>
    </div>

    <!-- Logs -->
    <div id="log-area">
      <div id="log-empty">&#x2190; select a project to view logs and controls</div>
    </div>

  </div>
</div>

<script>
const _K = "__NEXUS_API_KEY__";
let _proj = null;
let _sse  = null;
let _poll = null;
let _pd   = {};   // project_id → {status, port, pid}

// ── API ─────────────────────────────────────────────────────────────────────

async function api(url, opts) {
  return fetch(url, {
    ...(opts || {}),
    headers: { "X-API-Key": _K, ...((opts || {}).headers || {}) },
  });
}

// ── Projects ─────────────────────────────────────────────────────────────────

const _STATUS_URL = 'http://127.0.0.1:8001/status';

async function refresh() {
  try {
    const res = await fetch(_STATUS_URL);
    if (!res.ok) { console.error('fetch /status error:', res.status); return; }
    const data = await res.json();
    const apps = data.apps || [];

    // Build process-data index keyed by name
    const idx = {};
    for (const a of apps) idx[a.name] = a;
    _pd = idx;

    renderSidebar(apps);
    document.getElementById('ts').textContent = 'synced ' + new Date().toLocaleTimeString();
  } catch (e) { console.error('refresh', e); }
}

function renderSidebar(apps) {
  const list = document.getElementById('project-list');
  document.getElementById('proj-count').textContent = apps.length;

  if (!apps.length) {
    list.innerHTML = '<div style="padding:12px;color:#333;font-size:11px">No projects in generated_apps/</div>';
    return;
  }

  list.innerHTML = apps.map(a => {
    const st  = a.status || 'unknown';
    const sc  = 's-' + st;
    const act = _proj === a.name ? ' active' : '';
    const portHtml = a.port
      ? `<span class="port-tag">:${a.port}</span>`
      : `<span class="files-tag">stopped</span>`;
    return `<div class="proj-item${act}" data-id="${a.name}" onclick="pick('${a.name}')">
      <div class="pj-name" title="${a.name}">${a.name}</div>
      <div class="pj-meta">
        <span class="sdot ${sc}">&#x25CF;</span>
        <span class="${sc}">${st}</span>
        ${portHtml}
      </div>
    </div>`;
  }).join('');
}

// ── Select project ────────────────────────────────────────────────────────────

function pick(id) {
  _proj = id;

  document.querySelectorAll('.proj-item')
    .forEach(el => el.classList.toggle('active', el.dataset.id === id));

  const lbl = document.getElementById('proj-lbl');
  lbl.textContent = id;
  lbl.className = 'sel';

  document.getElementById('statusbar').style.display = 'flex';
  document.getElementById('btn-restart').disabled = false;

  const pr = _pd[id] || {};
  renderStatus(pr);
  setButtons(pr.status);

  clearLog('Connecting…');
  openSSE(id);

  if (_poll) clearInterval(_poll);
  _poll = setInterval(() => pollProc(id), 1500);
}

// ── Status UI ─────────────────────────────────────────────────────────────────

function renderStatus(pr) {
  const st   = pr.status || 'unknown';
  const sc   = 's-' + st;
  const port = pr.port;
  const pid  = pr.pid;

  const dot  = document.getElementById('sb-sdot');
  const text = document.getElementById('sb-stext');
  if (dot)  { dot.className  = 'sdot ' + sc; }
  if (text) { text.textContent = st; text.className = sc; }

  // Port
  const portRow = document.getElementById('sb-port-row');
  const portEl  = document.getElementById('sb-port');
  portRow.style.display = port ? 'flex' : 'none';
  if (portEl) portEl.textContent = port ? ':' + port : '';

  // PID
  const pidRow = document.getElementById('sb-pid-row');
  const pidEl  = document.getElementById('sb-pid');
  pidRow.style.display = pid ? 'flex' : 'none';
  if (pidEl) pidEl.textContent = pid || '';

  // Open button
  const ob = document.getElementById('open-btn');
  if (ob) {
    if (port) {
      ob.href = 'http://127.0.0.1:' + port;
      ob.textContent = '\U0001F517 Open :' + port;
      ob.style.display = 'inline-block';
    } else {
      ob.style.display = 'none';
    }
  }
}

function setButtons(status) {
  const running = status === 'running';
  const s = document.getElementById('btn-start');
  const t = document.getElementById('btn-stop');
  if (s) s.disabled = running;
  if (t) t.disabled = !running;
}

// ── Logs ─────────────────────────────────────────────────────────────────────

function clearLog(msg) {
  const el = document.getElementById('log-area');
  el.innerHTML = msg ? `<span class="ll ll-sys">${msg}</span>` : '';
}

function pushLog(line) {
  const el = document.getElementById('log-area');
  const empty = el.querySelector('#log-empty');
  if (empty) empty.remove();

  const span = document.createElement('span');
  span.className = 'll';
  if (/error|exception|traceback/i.test(line)) span.classList.add('ll-err');
  else if (/warn/i.test(line))  span.classList.add('ll-warn');
  else if (/\\binfo\\b/i.test(line)) span.classList.add('ll-info');

  span.textContent = line;
  const bot = el.scrollHeight - el.clientHeight <= el.scrollTop + 20;
  el.appendChild(span);
  if (bot) el.scrollTop = el.scrollHeight;
}

// ── SSE ───────────────────────────────────────────────────────────────────────

function openSSE(id) {
  if (_sse) { _sse.close(); _sse = null; }
  document.cookie = `nexus_api_key=${_K}; path=/; SameSite=Strict`;

  const sse = new EventSource('/process/stream/' + id);
  _sse = sse;

  sse.onmessage = e => pushLog(e.data);

  sse.addEventListener('status', e => {
    const d = JSON.parse(e.data);
    if (!_pd[id]) _pd[id] = {};
    Object.assign(_pd[id], d);
    renderStatus(_pd[id]);
    setButtons(d.status);
  });

  sse.addEventListener('end', () => {
    pushLog('─── stream ended ───');
    sse.close(); _sse = null;
  });

  sse.onerror = () => {
    if (sse.readyState === EventSource.CLOSED) _sse = null;
  };
}

// ── Status poll ───────────────────────────────────────────────────────────────

async function pollProc(id) {
  try {
    const res = await api('/process/' + id);
    const pr = res.ok
      ? await res.json()
      : { status: 'stopped', port: null, pid: null, logs: [] };

    if (!_pd[id]) _pd[id] = {};
    Object.assign(_pd[id], pr);

    if (id === _proj) {
      renderStatus(_pd[id]);
      setButtons(pr.status);
    }

    // Update sidebar dot without full re-render
    const item = document.querySelector(`.proj-item[data-id="${id}"]`);
    if (item) {
      const dot  = item.querySelector('.sdot');
      const txt  = item.querySelector('.pj-meta span:nth-child(2)');
      const sc   = 's-' + (pr.status || 'unknown');
      if (dot) dot.className = 'sdot ' + sc;
      if (txt) { txt.textContent = pr.status || 'unknown'; txt.className = sc; }

      // Update port tag if newly available
      const ptag = item.querySelector('.port-tag');
      const ftag = item.querySelector('.files-tag');
      if (pr.port && !ptag && ftag) {
        const span = document.createElement('span');
        span.className = 'port-tag';
        span.textContent = ':' + pr.port;
        ftag.replaceWith(span);
      }
    }
  } catch (_) {}
}

// ── Controls ─────────────────────────────────────────────────────────────────

async function doStart() {
  if (!_proj) return;
  const btn = document.getElementById('btn-start');
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const res = await api('/process/' + _proj + '/start', { method: 'POST' });
    if (res.ok) {
      clearLog('Starting…');
      openSSE(_proj);
    } else {
      pushLog('ERROR: ' + await res.text());
    }
  } catch (e) { pushLog('ERROR: ' + e.message); }
  finally { if (btn) btn.textContent = '▶ Start'; }
}

async function doStop() {
  if (!_proj) return;
  try {
    const res = await api('/process/' + _proj + '/stop', { method: 'POST' });
    if (!res.ok) pushLog('ERROR: ' + await res.text());
  } catch (e) { pushLog('ERROR: ' + e.message); }
}

async function doRestart() {
  if (!_proj) return;
  try {
    const res = await api('/process/' + _proj + '/restart', { method: 'POST' });
    if (res.ok) { clearLog('Restarting…'); openSSE(_proj); }
    else pushLog('ERROR: ' + await res.text());
  } catch (e) { pushLog('ERROR: ' + e.message); }
}

// ── Boot ─────────────────────────────────────────────────────────────────────
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the single-page project dashboard with API key injected."""
    return HTMLResponse(_HTML.replace("__NEXUS_API_KEY__", API_KEY))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.dashboard:app", host="0.0.0.0", port=8080, reload=True)
