"""
core/auto_loop_engine.py
=========================
AutoLoopEngine — automatic test → diagnose → fix → retry cycle for generated apps.

Flow per iteration
------------------
1. Wait until the process is registered as running and a port is detected.
2. Test backend: scan process logs for Python errors, then probe HTTP endpoints.
3. Test frontend: parse index.html for fetch URL problems.
4. Diagnose the first error found.
5. Apply a deterministic fix to backend.py or index.html.
6. Restart the process via RuntimeEngine.
7. Repeat (max MAX_ITERATIONS times).

No AI is used — only simple regex heuristics and HTTP probes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import httpx

from core.auto_loop_fixes import apply_fix
from core.auto_loop_improvements import apply_improvements

logger = logging.getLogger(__name__)
_P = "[AUTOLOOP]"   # log prefix

MAX_ITERATIONS  = 5
STARTUP_TIMEOUT = 10.0   # seconds to wait for process to come up
HTTP_TIMEOUT    = 5.0    # seconds per HTTP request
RESTART_PAUSE   = 2.0    # seconds to wait after stop before re-launching

# Endpoints that must return 200; add more as needed.
REQUIRED_ENDPOINTS: list[str] = ["/ping", "/time"]


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class TestResult:
    passed:     bool
    error_type: str = ""
    detail:     str = ""
    response:   Optional[httpx.Response] = field(default=None, repr=False, compare=False)
    exception:  Optional[Exception]      = field(default=None, repr=False, compare=False)

    def __str__(self) -> str:
        return f"passed={self.passed} type={self.error_type!r} detail={self.detail!r}"


# ── Engine ─────────────────────────────────────────────────────────────────────

class AutoLoopEngine:
    """
    Runs a test-fix-retry loop for a generated project.

    Usage:
        engine = AutoLoopEngine()
        healthy = await engine.run("app_123", Path("generated_apps/app_123"), port=8765)
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(
        self,
        project_id: str,
        project_path: Path,
        port: int = 0,
        expected_responses: Optional[dict] = None,
    ) -> bool:
        """
        Entry point.  Returns True when the app is HEALTHY, False after all
        iterations are exhausted without success.

        ``port`` is a hint only — the engine always re-reads the real port
        from RuntimeEngine/ProcessManager so it never uses a stale value.
        """
        project_path = Path(project_path).resolve()
        logger.info("%s Starting for '%s'  hint_port=%s  max_iter=%d",
                    _P, project_id, port or "auto", MAX_ITERATIONS)

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("%s ── Iteration %d/%d ──", _P, iteration, MAX_ITERATIONS)

            # 1. Wait for process running AND port detected by RuntimeEngine
            real_port = await self._wait_running(project_id, STARTUP_TIMEOUT)
            if real_port is None:
                logger.warning("%s Process not running or port not detected — aborting", _P)
                return False

            logger.info("%s Testing on port: %s", _P, real_port)

            # 1b. Proactively strip reload=True before touching the process.
            #     This MUST happen before any HTTP test so we never modify a
            #     file while StatReload is active — that is the crash vector.
            self._sanitize_reload(project_path)

            # 2+3. Run full test suite using the port from RuntimeEngine
            result = await self._run_tests(
                project_id, real_port, project_path,
                expected_responses=expected_responses or {},
            )
            logger.info("%s Test result: %s", _P, result)

            if result.passed:
                logger.info("%s ✅ '%s' is HEALTHY on port %s", _P, project_id, real_port)
                return await self._run_improvements(
                    project_id, project_path, real_port
                )

            # 4. Classify error using analyze_error
            from core.runtime.process_manager import get_manager as _gm
            _entry = _gm().get(project_id)
            _proc_logs = "\n".join((_entry.get("logs") or [])[-40:]) if _entry else ""
            error_type = self.analyze_error(result.response, result.exception, _proc_logs)
            logger.info("%s Error type detected: %s", _P, error_type)

            # 5. Special routing before fix
            if error_type == "timeout":
                logger.info("%s Applying fix: retry_delay", _P)
                await asyncio.sleep(RESTART_PAUSE * 2)
                continue

            if error_type == "unknown":
                logger.warning("%s Applying fix: none — stopping loop", _P)
                return False

            # 6. Apply targeted fix
            fix_name, fixed = self._route_fix(error_type, result, project_path)
            logger.info("%s Applying fix: %s", _P, fix_name)

            if not fixed:
                logger.warning("%s No fix available for '%s' — skipping restart",
                               _P, error_type)
                if iteration < MAX_ITERATIONS:
                    logger.info("%s Retrying in %.1fs…", _P, RESTART_PAUSE)
                    await asyncio.sleep(RESTART_PAUSE)
                continue

            # 7. Restart (skip on last iteration — no point)
            if iteration < MAX_ITERATIONS:
                logger.info("%s restarting app: '%s'", _P, project_id)
                await self._restart(project_id, project_path)
                logger.info("%s App restarted — retrying…", _P)

        logger.error("%s ❌ '%s' marked FAILED after %d iterations",
                     _P, project_id, MAX_ITERATIONS)
        return False

    # ── Wait for process ───────────────────────────────────────────────────────

    async def _wait_running(self, project_id: str, timeout: float) -> Optional[int]:
        """
        Poll ProcessManager until the process is running AND a port has been
        detected from RuntimeEngine's log parsing.

        Returns the real port (int) assigned by RuntimeEngine, or None on timeout.
        The port is always sourced from the DB — never from a caller constant.
        """
        from core.runtime.process_manager import get_manager
        manager = get_manager()
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            manager.sync_from_db()
            entry = manager.get(project_id)
            if entry and entry.get("status") == "running":
                raw_port = entry.get("port")
                if raw_port:
                    try:
                        real_port = int(raw_port)
                        logger.info("%s Process running — port=%s  pid=%s",
                                    _P, real_port, entry.get("pid"))
                        return real_port
                    except (ValueError, TypeError):
                        logger.warning("%s Invalid port value in DB: %r", _P, raw_port)
            await asyncio.sleep(0.5)
        logger.warning("%s Timeout waiting for '%s' to start / detect port", _P, project_id)
        return None

    # ── Tests ─────────────────────────────────────────────────────────────────

    async def _run_tests(
        self,
        project_id: str,
        port: int,
        project_path: Path,
        expected_responses: Optional[dict] = None,
    ) -> TestResult:
        """Run all checks in order; return first failure or success."""

        # Check Python process logs before hitting HTTP
        result = self._check_logs(project_id)
        if not result.passed:
            return result

        # HTTP probes
        result = await self._test_http(port, expected_responses=expected_responses or {})
        if not result.passed:
            return result

        # Frontend analysis
        result = self._test_frontend(project_path, port)
        if not result.passed:
            return result

        return TestResult(passed=True)

    # ── Error classifier ──────────────────────────────────────────────────────

    def analyze_error(
        self,
        response: Optional[httpx.Response],
        exception: Optional[Exception],
        logs: str,
    ) -> str:
        """
        Classify a failure into a canonical error type.

        Returns one of:
            "missing_endpoint" | "cors_error" | "server_error" |
            "frontend_error"   | "timeout"    | "wrong_response" |
            "wrong_ping_response" | "wrong_time_response" | "unknown"
        """
        if exception is not None:
            if isinstance(exception, (httpx.TimeoutException, asyncio.TimeoutError)):
                return "timeout"

        if response is not None:
            response_text = ""
            try:
                response_text = response.text
            except Exception:
                pass

            if response.status_code == 404:
                return "missing_endpoint"
            if response.status_code >= 500:
                return "server_error"
            if "CORS" in response_text or "CORS" in logs:
                return "cors_error"

        if "CORS" in logs:
            return "cors_error"
        if "Failed to fetch" in logs or "TypeError" in logs:
            return "frontend_error"

        return "unknown"

    # ── Phase 2: narrow error type from result.error_type ────────────────────
    # analyze_error above returns a broad category.  The actual error_type
    # stored in TestResult.error_type (e.g. "wrong_ping_response") is more
    # specific and is used by _route_fix.


    # ── Fix router ────────────────────────────────────────────────────────────

    def _route_fix(
        self,
        error_type: str,
        result: "TestResult",
        project_path: Path,
    ) -> Tuple[str, bool]:
        """
        Map a classified error type to a targeted fix. Returns (fix_name, fixed).

        Phase 2: handles wrong_ping_response, wrong_time_response.
        """
        # ── Phase 2: wrong response structure ────────────────────────────────
        if error_type == "wrong_ping_response":
            logger.info("%s 🔧 Fixing backend response — /ping must return {\"message\": \"pong\"}", _P)
            fixed = apply_fix("wrong_ping_response", project_path)
            return "wrong_ping_response", fixed

        if error_type == "wrong_time_response":
            logger.info("%s 🔧 Fixing backend response — /time must return ISO timestamp", _P)
            fixed = apply_fix("wrong_time_response", project_path)
            return "wrong_time_response", fixed

        if error_type == "wrong_response":
            logger.info("%s 🔧 Fixing backend response — generic wrong JSON structure", _P)
            fixed = apply_fix(result.error_type, project_path, error_detail=result.detail)
            return "wrong_response_fix", fixed

        if error_type == "missing_endpoint":
            fixed = apply_fix(result.error_type, project_path, error_detail=result.detail)
            return "endpoint_fixer", fixed

        if error_type == "cors_error":
            fixed = apply_fix("cors_error", project_path)
            return "cors_middleware", fixed

        if error_type == "server_error":
            logger.info("%s Capturing server logs before restart: %s", _P, result.detail)
            return "restart_and_capture", True

        if error_type == "frontend_error":
            fixed = apply_fix("absolute_fetch_url", project_path)
            return "frontend_patch", fixed

        # Fallback: delegate to existing error-type dispatch
        fixed = apply_fix(result.error_type, project_path, error_detail=result.detail)
        return result.error_type or "generic_fix", fixed


    # ── Log checker ───────────────────────────────────────────────────────────

    def _check_logs(self, project_id: str) -> TestResult:
        """Scan the last 40 log lines for common Python errors."""
        from core.runtime.process_manager import get_manager
        entry = get_manager().get(project_id)
        if not entry:
            return TestResult(passed=True)

        tail = "\n".join((entry.get("logs") or [])[-40:])

        patterns: list[tuple[str, str]] = [
            (r"ModuleNotFoundError[^\n]*",  "import_error"),
            (r"ImportError[^\n]*",          "import_error"),
            (r"SyntaxError[^\n]*",          "syntax_error"),
            (r"IndentationError[^\n]*",     "syntax_error"),
            (r"\w+Error[^\n]*",             "runtime_error"),
        ]

        for pattern, err_type in patterns:
            if err_type == "runtime_error" and "Traceback" not in tail:
                continue
            m = re.search(pattern, tail)
            if m:
                return TestResult(False, err_type, m.group(0).strip())

        return TestResult(passed=True)

    # ── HTTP checker ──────────────────────────────────────────────────────────

    async def _test_http(
        self,
        port: int,
        expected_responses: Optional[dict] = None,
    ) -> TestResult:
        """
        Probe every endpoint in REQUIRED_ENDPOINTS plus GET /.

        For REQUIRED_ENDPOINTS: a 404 → missing_endpoint_<slug> error.
        For GET /: a 404 → missing_index_route error.
        A 5xx on any probe → server_error.
        ConnectError on the first probe → connection_refused (app not up yet).

        Phase 2: validates response *content* for /ping and /time.
        Bug #7 fix: also compares against caller-supplied expected_responses dict.
        """
        expected_responses = expected_responses or {}
        base = f"http://127.0.0.1:{port}"
        logger.info("%s 🔁 Retesting on port: %s", _P, port)


        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:

                # ── Required endpoints ────────────────────────────────────────
                for ep in REQUIRED_ENDPOINTS:
                    url = f"{base}{ep}"
                    try:
                        r = await client.get(url)
                        logger.info("%s GET %s → %s", _P, ep, r.status_code)
                        if r.status_code == 404:
                            slug = ep.lstrip("/").replace("/", "_") or "root"
                            return TestResult(
                                False,
                                f"missing_endpoint_{slug}",
                                f"GET {ep} returned 404 — endpoint missing in backend.py",
                                response=r,
                            )
                        if r.status_code >= 500:
                            return TestResult(
                                False, "server_error",
                                f"GET {ep} returned {r.status_code}",
                                response=r,
                            )

                        # ── Phase 2: Response content validation ────────────
                        if r.status_code == 200:
                            try:
                                body = r.json()
                            except Exception:
                                return TestResult(
                                    False, "wrong_response",
                                    f"GET {ep} returned non-JSON: {r.text[:200]}",
                                    response=r,
                                )

                            # Bug #7 fix: compare against caller-supplied expected
                            if ep in expected_responses:
                                expected = expected_responses[ep]
                                if body != expected:
                                    return TestResult(
                                        False, "wrong_response",
                                        (
                                            f"GET {ep}: expected {expected} "
                                            f"but got {body}"
                                        ),
                                        response=r,
                                    )

                            if ep == "/ping":
                                # Must return {"message": "pong"}
                                if not isinstance(body, dict) or body.get("message") != "pong":
                                    return TestResult(
                                        False, "wrong_ping_response",
                                        f"GET /ping returned unexpected JSON: {body}",
                                        response=r,
                                    )

                            if ep == "/time":
                                # Must return a dict with a valid ISO timestamp
                                time_val = body.get("time") if isinstance(body, dict) else None
                                if not time_val or not isinstance(time_val, str):
                                    return TestResult(
                                        False, "wrong_time_response",
                                        f"GET /time missing 'time' field: {body}",
                                        response=r,
                                    )
                                # Validate ISO format: contains T and Z or +/- offset
                                if "T" not in time_val:
                                    return TestResult(
                                        False, "wrong_time_response",
                                        f"GET /time returned non-ISO timestamp: {time_val}",
                                        response=r,
                                    )

                    except httpx.ConnectError as exc:
                        return TestResult(
                            False, "connection_refused",
                            f"Cannot connect to 127.0.0.1:{port}",
                            exception=exc,
                        )
                    except httpx.TimeoutException as exc:
                        return TestResult(
                            False, "timeout",
                            f"Timeout on 127.0.0.1:{port}",
                            exception=exc,
                        )


                # ── GET / — must serve index.html, not 404 ───────────────────
                try:
                    r = await client.get(f"{base}/")
                    logger.info("%s GET / → %s", _P, r.status_code)
                    if r.status_code == 404:
                        return TestResult(
                            False, "missing_index_route",
                            "GET / returns 404 — need FileResponse('index.html') endpoint",
                            response=r,
                        )
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass

        except Exception as exc:
            logger.warning("%s Unexpected HTTP error: %s", _P, exc)

        return TestResult(passed=True)

    # ── Frontend checker ──────────────────────────────────────────────────────

    def _test_frontend(self, project_path: Path, port: int) -> TestResult:
        """
        Parse index.html for fetch() URL problems.

        Phase 2 — checks:
          - absolute http://host:PORT URLs (will break on port change)
          - "Failed to fetch" hardcoded in JS strings (likely from bad template)
          - wrong endpoint paths (e.g. fetch('/api/ping') instead of fetch('/ping'))
          - fetch calls that don't use relative paths at all

        Correct pattern : fetch('/ping')            — relative, same-origin via GET /
        Bad pattern     : fetch('http://...:{port}') — absolute, breaks on restart
        """
        html_path = project_path / "index.html"
        if not html_path.exists():
            return TestResult(passed=True)

        content = html_path.read_text(encoding="utf-8", errors="replace")

        # ── 1. Absolute URL with any hardcoded port — will break on restart
        m = re.search(
            r"""fetch\s*\(\s*['"]http://(?:localhost|127\.0\.0\.1):(\d+)(/[^'"]*)""",
            content,
        )
        if m:
            hardcoded_port = m.group(1)
            path = m.group(2)
            return TestResult(
                False, "absolute_fetch_url",
                f"fetch() uses absolute http://...:{hardcoded_port}{path} — must use relative '{path}'",
            )

        # ── 2. "Failed to fetch" hardcoded in JS (not in catch block — that's fine)
        #    Look for "Failed to fetch" as a literal string used outside of catch()
        if '"Failed to fetch"' in content or "'Failed to fetch'" in content:
            return TestResult(
                False, "frontend_error",
                "index.html contains hardcoded 'Failed to fetch' string — fetch URL likely wrong",
            )

        # ── 3. Wrong endpoint: fetch('/api/ping') instead of fetch('/ping')
        wrong_endpoints = re.findall(
            r"""fetch\s*\(\s*['"](/api/[^'"]*)""",
            content,
        )
        if wrong_endpoints:
            bad_path = wrong_endpoints[0]
            return TestResult(
                False, "frontend_error",
                f"index.html uses wrong endpoint '{bad_path}' — should be '/ping' or '/time'",
            )

        # relative fetch('/path') is CORRECT when GET / serves index.html — no error
        return TestResult(passed=True)


    # ── Phase 3.2: improvement pass ──────────────────────────────────────────

    async def _run_improvements(
        self, project_id: str, project_path: Path, port: int
    ) -> bool:
        """
        Run the non-critical improvement pass exactly once after the app is
        confirmed healthy.

        Contract
        --------
        - Always returns True (the app was healthy; improvements are optional).
        - If improvements were applied: restart the process, then re-test once
          to verify nothing was broken.  A re-test failure is logged as a
          warning but does NOT flip the return value to False.
        - Maximum 1 improvement cycle — no loop.
        """
        improvements = apply_improvements(project_path)

        if not improvements:
            return True  # nothing to do — already polished

        logger.info("%s Improvements applied: %s", _P, improvements)
        logger.info("%s Restarting after improvements", _P)
        await self._restart(project_id, project_path)

        logger.info("%s Re-testing after improvements", _P)
        re_port = await self._wait_running(project_id, STARTUP_TIMEOUT)
        if re_port is None:
            logger.warning(
                "%s Process did not come back after improvements — "
                "marking healthy anyway (improvements are non-critical)",
                _P,
            )
            return True

        retest = await self._run_tests(project_id, re_port, project_path)
        if retest.passed:
            logger.info(
                "%s ✅ '%s' still HEALTHY after improvements", _P, project_id
            )
        else:
            logger.warning(
                "%s Re-test failed after improvements: %s — "
                "app was healthy before; improvements are non-critical",
                _P, retest,
            )

        return True  # healthy regardless of improvement re-test outcome

    # ── Sanitize: strip reload before any file modification ──────────────────

    def _sanitize_reload(self, project_path: Path) -> None:
        """
        Always called at the top of every iteration BEFORE any HTTP probe or
        fix is applied.

        Strips ``reload=True`` from backend.py so that StatReload can never
        race with RuntimeEngine's controlled restarts.  Safe to call even when
        the process is already running — we only modify the *source file*, not
        the running process.  On the next restart RuntimeEngine will load the
        clean version.

        If the file was already clean (common path) this is a cheap no-op.
        """
        from core.auto_loop_fixes import _fix_strip_reload
        changed = _fix_strip_reload(project_path / "backend.py")
        if changed:
            logger.info(
                "%s Sanitized reload=True from backend.py — "
                "RuntimeEngine is the sole restart controller",
                _P,
            )

    # ── Fixes — delegated to core.auto_loop_fixes ────────────────────────────
    # All fix logic lives in auto_loop_fixes.apply_fix().
    # This method is kept for logging consistency; callers use apply_fix() directly.

    # ── Restart ───────────────────────────────────────────────────────────────

    async def _restart(self, project_id: str, project_path: Path) -> None:
        from core.runtime.process_manager import get_manager
        from core.runtime.runtime_engine import get_engine

        manager = get_manager()
        manager.stop(project_id)
        logger.info("%s Process stopped, waiting %.1fs…", _P, RESTART_PAUSE)
        await asyncio.sleep(RESTART_PAUSE)

        launched = await get_engine().launch(project_id, project_path)
        if launched:
            logger.info("%s '%s' restarted successfully", _P, project_id)
        else:
            logger.warning("%s Failed to restart '%s'", _P, project_id)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[AutoLoopEngine] = None


def get_loop_engine() -> AutoLoopEngine:
    global _instance
    if _instance is None:
        _instance = AutoLoopEngine()
    return _instance
