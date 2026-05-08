"""
core/auto_loop_improvements.py
================================
Phase 3.2 — post-healthy improvement pass for AutoLoopEngine.

Runs ONCE after the app passes all health checks.  Each improvement is
fully idempotent: it inspects the current file content and skips itself
if the feature is already present, so re-running on the same project is
always safe.

Public API
----------
    apply_improvements(project_path: Path) -> list[str]

Returns the list of improvement labels that were applied.
An empty list means nothing changed and no restart is needed.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
_P = "[IMPROVEMENTS]"


# ── Public entry point ────────────────────────────────────────────────────────

def apply_improvements(project_path: Path) -> list[str]:
    """
    Inspect and enhance the generated app in *project_path*.

    Improvements are applied in dependency order so that later ones can
    rely on elements inserted by earlier ones (e.g. error-handling uses
    #status injected by the status-indicator improvement).

    Returns the list of improvement labels that were actually applied.
    Callers should restart the process when the list is non-empty.
    """
    project_path = Path(project_path)
    backend_path = project_path / "backend.py"
    html_path    = project_path / "index.html"

    applied: list[str] = []

    backend_src = backend_path.read_text(encoding="utf-8") if backend_path.exists() else ""
    html_src    = html_path.read_text(encoding="utf-8")    if html_path.exists()    else ""

    if not html_src:
        logger.debug("%s index.html not found — skipping improvements", _P)
        return applied

    html = html_src

    # ── D) Normalize fetch URLs ───────────────────────────────────────────────
    changed, html = _improve_normalize_fetch(html)
    if changed:
        applied.append("normalize_fetch")

    # ── B) Status indicator ───────────────────────────────────────────────────
    # Must run before error-handling so #status exists when the catch block
    # tries to write to it.
    changed, html = _improve_status_indicator(html)
    if changed:
        applied.append("status_indicator")

    # ── C) Fetch error handling ───────────────────────────────────────────────
    changed, html = _improve_fetch_error_handling(html)
    if changed:
        applied.append("fetch_error_handling")

    # ── A) /time button ───────────────────────────────────────────────────────
    # Only inject if the backend actually exposes /time.
    if '"/time"' in backend_src or "'/time'" in backend_src:
        changed, html = _improve_time_button(html)
        if changed:
            applied.append("time_button")

    if html != html_src:
        html_path.write_text(html, encoding="utf-8")
        logger.info("%s Wrote enhanced index.html — improvements: %s", _P, applied)

    return applied


# ── A) /time button ───────────────────────────────────────────────────────────

def _improve_time_button(html: str) -> tuple[bool, str]:
    """
    Add a 'Get Time' button wired to GET /time.

    Guard: skip if a button or fetch call for /time is already present.
    """
    if (
        "time-btn"       in html
        or 'fetch("/time")' in html
        or "fetch('/time')" in html
        or "/time"          in html   # already referenced somewhere
    ):
        return False, html

    button_snippet = (
        '\n  <button id="time-btn" onclick="fetchTime()">'
        "Get Time</button>\n"
        '  <p id="time-result"></p>'
    )

    time_js = """\

  function fetchTime() {
    fetch('/time')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var el = document.getElementById('time-result');
        if (el) el.textContent = data.time || JSON.stringify(data);
      })
      .catch(function(e) {
        var el = document.getElementById('time-result');
        if (el) el.textContent = 'Error: ' + e.message;
      });
  }"""

    html = _inject_before_body(html, button_snippet)
    html = _inject_into_script(html, time_js)
    return True, html


# ── B) Status indicator ───────────────────────────────────────────────────────

def _improve_status_indicator(html: str) -> tuple[bool, str]:
    """
    Inject a #status paragraph that pings /ping on page load and shows
    'OK' (green) or 'ERROR' (red).

    Guard: skip if id="status" already exists.
    """
    if 'id="status"' in html or "id='status'" in html:
        return False, html

    status_html = (
        '\n  <p id="status" style="color:grey;font-size:0.85em">'
        "Checking...</p>"
    )

    status_js = """\

  (function checkStatus() {
    fetch('/ping')
      .then(function(r) {
        var el = document.getElementById('status');
        if (!el) return;
        if (r.ok) { el.textContent = 'OK'; el.style.color = 'green'; }
        else      { el.textContent = 'ERROR ' + r.status; el.style.color = 'red'; }
      })
      .catch(function() {
        var el = document.getElementById('status');
        if (el) { el.textContent = 'ERROR'; el.style.color = 'red'; }
      });
  })();"""

    html = _inject_before_body(html, status_html)
    html = _inject_into_script(html, status_js)
    return True, html


# ── C) Fetch error handling ───────────────────────────────────────────────────

def _improve_fetch_error_handling(html: str) -> tuple[bool, str]:
    """
    Add a global unhandledrejection listener that surfaces any uncaught
    promise rejection (including failed fetch calls) in the #status element.

    Using a global handler is safer than rewriting individual fetch chains
    with regex — it has zero chance of breaking existing JS syntax.

    Guard: skip if unhandledrejection is already handled.
    """
    if "unhandledrejection" in html or not re.search(r"fetch\s*\(", html):
        return False, html

    error_js = """\

  window.addEventListener('unhandledrejection', function(e) {
    var msg = e.reason && (e.reason.message || String(e.reason)) || 'Unknown error';
    var el = document.getElementById('status');
    if (el) { el.textContent = 'Error: ' + msg; el.style.color = 'red'; }
    console.error('Unhandled rejection:', e.reason);
  });"""

    html = _inject_into_script(html, error_js)
    return True, html


# ── D) Normalize fetch URLs ───────────────────────────────────────────────────

def _improve_normalize_fetch(html: str) -> tuple[bool, str]:
    """
    Replace ``fetch('http://localhost:PORT/path')`` with ``fetch('/path')``.

    Absolute URLs break when the app is restarted on a different port.
    Relative URLs resolve against the same origin that served index.html.
    """
    new_html = re.sub(
        r"""(fetch\s*\(\s*['"])http://(?:localhost|127\.0\.0\.1):\d+(/[^'"]*)""",
        r"\1\2",
        html,
    )
    if new_html == html:
        return False, html
    return True, new_html


# ── HTML / JS injection helpers ───────────────────────────────────────────────

def _inject_before_body(html: str, snippet: str) -> str:
    """Insert *snippet* just before ``</body>``.  Falls back to appending."""
    tag = "</body>"
    if tag in html:
        return html.replace(tag, snippet + "\n" + tag, 1)
    return html + snippet


def _inject_into_script(html: str, js: str) -> str:
    """
    Append *js* inside the last existing ``<script>`` block.
    If no script block exists, create one before ``</body>``.

    Inserting before ``</script>`` (rather than after the opening tag)
    keeps the new code at the bottom of the block where it executes after
    any existing definitions it may depend on.
    """
    last = html.rfind("</script>")
    if last != -1:
        return html[:last] + js + "\n" + html[last:]

    # No existing script — wrap in a new block
    block = f"\n<script>{js}\n</script>"
    return _inject_before_body(html, block)
