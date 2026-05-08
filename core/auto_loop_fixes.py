"""
core/auto_loop_fixes.py
========================
Deterministic, port-agnostic fixes for AutoLoopEngine.

Public API
----------
    apply_fix(error_type, project_path, error_detail="") -> bool

Canonical error types
---------------------
    wrong_fetch_url         — absolute fetch('http://host:PORT/path') → relative fetch('/path')
    hardcoded_port          — alias for wrong_fetch_url
    missing_ping            — add GET /ping endpoint to backend.py
    missing_index           — add GET / FileResponse("index.html") to backend.py
    cors_error              — add CORSMiddleware to backend.py
    import_error            — add common missing imports (typing, pydantic)
    syntax_error            — attempt to strip trailing junk after the last valid line
    runtime_error           — no-op (logged for human review)
    missing_endpoint_<slug> — add a stub GET /<slug> endpoint to backend.py

Internal aliases (from AutoLoopEngine error types) are also accepted so the
engine can call apply_fix() directly without an extra mapping layer.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
_P = "[FIXES]"


# ── Public entry point ────────────────────────────────────────────────────────

def apply_fix(
    error_type: str,
    project_path: Path,
    error_detail: str = "",
) -> bool:
    """
    Apply the deterministic fix for *error_type* to the project at
    *project_path*.

    Returns True when at least one file was modified, False otherwise
    (including when the fix is not registered or already applied).

    Dynamic dispatch: ``missing_endpoint_<slug>`` maps to _fix_add_endpoint,
    where the slug encodes the URL path (e.g. "time" → GET /time).
    """
    project_path = Path(project_path)
    backend  = project_path / "backend.py"
    frontend = project_path / "index.html"

    _DISPATCH: dict[str, object] = {
        # Canonical names
        "wrong_fetch_url": lambda: _fix_fetch_url(frontend),
        "hardcoded_port":  lambda: _fix_fetch_url(frontend),
        "missing_ping":    lambda: _fix_add_ping(backend),
        "missing_index":   lambda: _fix_add_index_route(backend),
        "cors_error":      lambda: _fix_add_cors(backend),
        "import_error":    lambda: _fix_imports(error_detail, backend),
        "syntax_error":    lambda: _fix_syntax_error(error_detail, backend),
        "runtime_error":   lambda: _fix_runtime_error(error_detail, backend),
        "reload_conflict": lambda: _fix_strip_reload(backend),

        # Internal aliases (AutoLoopEngine error types)
        "absolute_fetch_url":   lambda: _fix_fetch_url(frontend),
        "404_ping":             lambda: _fix_add_ping(backend),
        "missing_index_route":  lambda: _fix_add_index_route(backend),
        "missing_cors":         lambda: _fix_add_cors(backend),
        "connection_refused":   lambda: _fix_host_binding(backend),

        # wrong_response fixes (Phase 2)
        "wrong_ping_response":  lambda: _fix_wrong_ping_response(backend),
        "wrong_time_response":  lambda: _fix_wrong_time_response(backend),
    }


    fn = _DISPATCH.get(error_type)

    # Dynamic: missing_endpoint_<slug>  e.g. missing_endpoint_time
    if fn is None and error_type.startswith("missing_endpoint_"):
        slug = error_type[len("missing_endpoint_"):]
        endpoint_path = "/" + slug.replace("_", "/")
        fn = lambda: _fix_add_endpoint(backend, endpoint_path)  # noqa: E731

    if fn is None:
        logger.debug("%s No fix registered for error_type='%s'", _P, error_type)
        return False

    result = bool(fn())  # type: ignore[operator]
    if result:
        logger.info("%s Fix applied: %s → %s", _P, error_type, project_path.name)
    else:
        logger.debug("%s Fix for '%s' made no changes (already applied?)", _P, error_type)
    return result


# ── Fix: convert absolute fetch URLs → relative ───────────────────────────────

def _fix_fetch_url(frontend: Path) -> bool:
    """
    Replace every ``fetch('http://host:PORT/path')`` with ``fetch('/path')``.

    Relative URLs are immune to port changes on restart — they resolve against
    the same origin that served index.html (via GET /).
    """
    if not frontend.exists():
        logger.debug("%s index.html not found — skipping fetch URL fix", _P)
        return False

    src = frontend.read_text(encoding="utf-8")
    original = src

    # fetch('http://localhost:PORT/path')  →  fetch('/path')
    # fetch('http://127.0.0.1:PORT/path') →  fetch('/path')
    src = re.sub(
        r"""(fetch\s*\(\s*['"])http://(?:localhost|127\.0\.0\.1):\d+(/[^'"]*)""",
        r"\1\2",
        src,
    )

    if src == original:
        return False

    frontend.write_text(src, encoding="utf-8")
    logger.info("%s Converted absolute fetch URLs to relative in index.html", _P)
    return True


# ── Fix: add GET /ping endpoint ───────────────────────────────────────────────

def _fix_add_ping(backend: Path) -> bool:
    """Insert a minimal ``GET /ping`` health-check endpoint into backend.py."""
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")

    if '"/ping"' in src or "'/ping'" in src:
        return False  # already present

    snippet = '\n\n@app.get("/ping")\ndef ping():\n    return {"message": "pong"}\n'

    if 'if __name__ == "__main__":' in src:
        src = src.replace(
            'if __name__ == "__main__":',
            snippet + '\nif __name__ == "__main__":',
        )
    else:
        src += snippet

    backend.write_text(src, encoding="utf-8")
    logger.info("%s Added GET /ping to backend.py", _P)
    return True


# ── Fix: add GET / FileResponse endpoint ─────────────────────────────────────

def _fix_add_index_route(backend: Path) -> bool:
    """
    Add ``GET /`` that serves ``index.html`` via ``FileResponse``.

    Without this, relative ``fetch('/ping')`` has no same-origin page to
    resolve against — the browser picks an arbitrary origin and CORS fails.
    """
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")

    if '@app.get("/")' in src or "@app.get('/')" in src:
        return False  # already present

    # Ensure FileResponse is imported
    if "FileResponse" not in src:
        if "from fastapi.responses import" in src:
            src = re.sub(
                r"(from fastapi\.responses import )([^\n]+)",
                lambda m: m.group(0)
                if "FileResponse" in m.group(2)
                else m.group(1) + m.group(2) + ", FileResponse",
                src,
                count=1,
            )
        else:
            src = "from fastapi.responses import FileResponse\n" + src

    snippet = '\n\n@app.get("/")\ndef index():\n    return FileResponse("index.html")\n'

    if '@app.get("/ping")' in src:
        src = src.replace('@app.get("/ping")', snippet + '\n@app.get("/ping")', 1)
    elif 'if __name__ == "__main__":' in src:
        src = src.replace(
            'if __name__ == "__main__":',
            snippet + '\nif __name__ == "__main__":',
            1,
        )
    else:
        src += snippet

    backend.write_text(src, encoding="utf-8")
    logger.info('%s Added GET / FileResponse("index.html") to backend.py', _P)
    return True


# ── Fix: add CORSMiddleware ───────────────────────────────────────────────────

def _fix_add_cors(backend: Path) -> bool:
    """Add ``CORSMiddleware`` (allow_origins=["*"]) to backend.py."""
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")

    if "CORSMiddleware" in src:
        return False  # already present

    cors_import = "from fastapi.middleware.cors import CORSMiddleware\n"
    cors_setup = (
        "\napp.add_middleware(\n"
        '    CORSMiddleware,\n'
        '    allow_origins=["*"],\n'
        '    allow_methods=["*"],\n'
        '    allow_headers=["*"],\n'
        ")\n"
    )

    # Insert import after last "from fastapi …" line
    lines = src.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from fastapi") or line.startswith("import fastapi"):
            insert_at = i + 1
    lines.insert(insert_at, cors_import)
    src = "".join(lines)

    # Insert middleware block after app = FastAPI(...)
    src = re.sub(
        r"(app\s*=\s*FastAPI\([^)]*\))",
        r"\1" + cors_setup,
        src,
        count=1,
    )

    backend.write_text(src, encoding="utf-8")
    logger.info("%s Added CORSMiddleware to backend.py", _P)
    return True


# ── Fix: strip uvicorn reload ─────────────────────────────────────────────────

def _fix_strip_reload(backend: Path) -> bool:
    """
    Remove ``reload=True`` (and the stale ``--reload`` string) from any
    ``uvicorn.run()`` call inside backend.py.

    LLMs routinely emit ``uvicorn.run(app, reload=True, ...)`` in the
    ``__main__`` block.  Even though RuntimeEngine launches the app via
    ``python -m uvicorn backend:app --port X`` (no --reload), having
    ``reload=True`` in the source is a latent hazard: if the file is ever
    run directly, StatReload activates and races with RuntimeEngine's own
    restart logic, producing ``RuntimeError: reentrant call``.

    This fix is also applied *proactively* at the start of every auto-loop
    iteration (via AutoLoopEngine._sanitize_reload) so the hazard is
    eliminated before any file modifications are made.
    """
    if not backend.exists():
        return False

    src = backend.read_text(encoding="utf-8")
    original = src

    # Remove reload=True, / reload=True (trailing comma and spaces variants)
    src = re.sub(r",?\s*reload\s*=\s*True\s*,?", _strip_kwarg_comma, src)

    # Remove reload=False as well (no benefit in generated apps — just noise)
    src = re.sub(r",?\s*reload\s*=\s*False\s*,?", _strip_kwarg_comma, src)

    if src == original:
        return False

    backend.write_text(src, encoding="utf-8")
    logger.info("%s Stripped reload=True from uvicorn.run() in backend.py", _P)
    return True


def _strip_kwarg_comma(m: re.Match) -> str:
    """
    Replacement helper: keep exactly one comma separator when the matched
    kwarg was between two other arguments (i.e. had commas on both sides).
    """
    text = m.group(0)
    leading_comma  = text.lstrip().startswith(",") or text.startswith(",")
    trailing_comma = text.rstrip().endswith(",")
    # Both sides had commas → keep one separator
    if leading_comma and trailing_comma:
        return ", "
    return ""


# ── Fix: host binding ─────────────────────────────────────────────────────────

def _fix_host_binding(backend: Path) -> bool:
    """Ensure ``uvicorn.run()`` binds to ``0.0.0.0`` so the app is reachable."""
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")

    if "uvicorn.run(" not in src or "host=" in src:
        return False

    src = src.replace("uvicorn.run(", 'uvicorn.run(host="0.0.0.0", ', 1)
    backend.write_text(src, encoding="utf-8")
    logger.info("%s Added host='0.0.0.0' to uvicorn.run()", _P)
    return True


# ── Fix: common missing imports ───────────────────────────────────────────────

def _fix_imports(detail: str, backend: Path) -> bool:
    """Add commonly missing imports inferred from the error message."""
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")
    changed = False

    if any(t in detail for t in ("List", "Dict", "Optional", "Any", "Tuple")):
        if "from typing import" not in src:
            src = "from typing import Any, Dict, List, Optional, Tuple\n" + src
            changed = True

    if "BaseModel" in detail and "from pydantic import" not in src:
        src = "from pydantic import BaseModel\n" + src
        changed = True

    if not changed:
        return False

    backend.write_text(src, encoding="utf-8")
    logger.info("%s Fixed missing imports in backend.py", _P)
    return True


# ── Fix: generic stub endpoint ────────────────────────────────────────────────

def _fix_add_endpoint(backend: Path, endpoint_path: str) -> bool:
    """
    Insert a minimal stub endpoint for *endpoint_path* (e.g. '/time') that
    returns a JSON object.  The function name is derived from the path slug.
    """
    if not backend.exists():
        return False
    src = backend.read_text(encoding="utf-8")

    # Already present?
    quoted = endpoint_path.replace("/", "/")
    if f'"{endpoint_path}"' in src or f"'{endpoint_path}'" in src:
        return False

    # Build a safe Python function name from the path
    func_name = endpoint_path.strip("/").replace("/", "_").replace("-", "_") or "root"

    # Build a meaningful default response depending on the path name
    if "time" in func_name:
        import_line = "import datetime\n"
        body = (
            "    return {\"time\": datetime.datetime.utcnow().isoformat() + \"Z\"}"
        )
    elif "health" in func_name or "status" in func_name:
        import_line = ""
        body = "    return {\"status\": \"ok\"}"
    else:
        import_line = ""
        body = f"    return {{\"endpoint\": \"{endpoint_path}\", \"ok\": True}}"

    snippet = f'\n\n@app.get("{endpoint_path}")\ndef {func_name}():\n{body}\n'

    # Prepend import if needed
    if import_line and import_line.strip() not in src:
        src = import_line + src

    # Insert before __main__ block or append
    if 'if __name__ == "__main__":' in src:
        src = src.replace(
            'if __name__ == "__main__":',
            snippet + '\nif __name__ == "__main__":',
            1,
        )
    else:
        src += snippet

    backend.write_text(src, encoding="utf-8")
    logger.info("%s Added stub GET %s to backend.py", _P, endpoint_path)
    return True


# ── Fix: syntax errors ────────────────────────────────────────────────────────

def _fix_syntax_error(detail: str, backend: Path) -> bool:
    """
    Attempt a minimal repair for syntax errors by finding the offending line
    number from the error message and commenting it out as a last resort.

    This is intentionally conservative: only acts when the line number is
    clearly stated in *detail* and the target line is not a structural keyword.
    """
    if not backend.exists():
        return False

    # Extract line number from e.g. "SyntaxError: invalid syntax (backend.py, line 42)"
    m = re.search(r"line\s+(\d+)", detail)
    if not m:
        logger.debug("%s Cannot extract line number from syntax error: %r", _P, detail)
        return False

    lineno = int(m.group(1)) - 1  # 0-indexed
    lines = backend.read_text(encoding="utf-8").splitlines(keepends=True)

    if lineno < 0 or lineno >= len(lines):
        return False

    bad_line = lines[lineno]
    # Never comment out structural lines — that would cascade more errors
    structural = ("def ", "class ", "if __name__", "import ", "from ")
    if any(bad_line.lstrip().startswith(k) for k in structural):
        logger.debug("%s Refusing to comment out structural line %d: %r",
                     _P, lineno + 1, bad_line.rstrip())
        return False

    lines[lineno] = "# [autoloop-removed] " + bad_line
    backend.write_text("".join(lines), encoding="utf-8")
    logger.info("%s Commented out offending line %d in backend.py", _P, lineno + 1)
    return True


# ── Fix: runtime errors ───────────────────────────────────────────────────────

def _fix_runtime_error(detail: str, backend: Path) -> bool:
    """
    Handle known runtime error patterns:
      - NameError: name 'X' is not defined  → add `X = None` near top
      - AttributeError / TypeError           → no deterministic fix; return False

    Returns False for unrecognised patterns so AutoLoopEngine knows no change
    was made and will log accordingly.
    """
    if not backend.exists():
        return False

    # NameError: name 'foo' is not defined
    m = re.search(r"NameError[^:]*:\s*name '(\w+)' is not defined", detail)
    if m:
        name = m.group(1)
        src = backend.read_text(encoding="utf-8")
        stub = f"{name} = None  # [autoloop] stub — replace with real value\n"
        if name in src:
            return False  # name exists somewhere; don't stomp it
        # Insert after imports block
        insert_after = _last_import_line(src)
        lines = src.splitlines(keepends=True)
        lines.insert(insert_after, stub)
        backend.write_text("".join(lines), encoding="utf-8")
        logger.info("%s Added stub '%s = None' to backend.py", _P, name)
        return True

    logger.debug("%s No deterministic fix for runtime_error: %r", _P, detail)
    return False


def _last_import_line(src: str) -> int:
    """Return the 0-indexed line number just after the last top-level import."""
    last = 0
    for i, line in enumerate(src.splitlines()):
        if line.startswith("import ") or line.startswith("from "):
            last = i + 1
    return last


# ── Fix: wrong /ping response structure ───────────────────────────────────────

def _fix_wrong_ping_response(backend: Path) -> bool:
    """
    Fix the response body of GET /ping when it doesn't return
    ``{"message": "pong"}``.

    Scans for any ``@app.get("/ping")`` handler and replaces its ``return``
    statement with the canonical response.
    """
    if not backend.exists():
        return False

    src = backend.read_text(encoding="utf-8")

    if '{"message": "pong"}' in src:
        return False  # already correct

    # Find the /ping endpoint function and replace its return statement
    # Pattern: the function definition after @app.get("/ping")
    m = re.search(
        r'(@app\.get\s*\(\s*["\']/ping["\']\s*\)'
        r'\s*\n\s*def\s+\w+\s*\([^)]*\)\s*:\s*\n)(.*?)(?=\n\s*@app\.|\n\s*if __name__|\Z)',
        src,
        re.DOTALL,
    )
    if m:
        header = m.group(1)
        # Replace the entire body with the canonical return
        new_body = '    return {"message": "pong"}\n'
        src = src[: m.start(2)] + new_body + src[m.end(2) :]
        backend.write_text(src, encoding="utf-8")
        logger.info("%s Fixed wrong /ping response → {\"message\": \"pong\"}", _P)
        return True

    logger.debug("%s Could not locate /ping handler in backend.py", _P)
    return False


# ── Fix: wrong /time response structure ───────────────────────────────────────

def _fix_wrong_time_response(backend: Path) -> bool:
    """
    Fix the response body of GET /time when it doesn't return a valid ISO
    timestamp.

    Replaces the return statement of the /time handler with a proper ISO
    UTC timestamp response.  Also ensures ``import datetime`` is present.
    """
    if not backend.exists():
        return False

    src = backend.read_text(encoding="utf-8")

    # Ensure datetime is imported
    if "import datetime" not in src:
        src = "import datetime\n" + src

    # Check if /time already has the correct response
    if 'datetime.datetime.utcnow().isoformat()' in src:
        return False  # already correct


    # Find the /time endpoint function and replace its return statement
    m = re.search(
        r'(@app\.get\s*\(\s*["\']/time["\']\s*\)'
        r'\s*\n\s*def\s+\w+\s*\([^)]*\)\s*:\s*\n)(.*?)(?=\n\s*@app\.|\n\s*if __name__|\Z)',
        src,
        re.DOTALL,
    )
    if m:
        header = m.group(1)
        # Replace the body with proper ISO timestamp response
        new_body = (
            '    return {"time": datetime.datetime.utcnow().isoformat() + "Z"}\n'
        )
        src = src[: m.start(2)] + new_body + src[m.end(2) :]
        backend.write_text(src, encoding="utf-8")
        logger.info("%s Fixed wrong /time response → ISO timestamp", _P)
        return True

    logger.debug("%s Could not locate /time handler in backend.py", _P)
    return False

