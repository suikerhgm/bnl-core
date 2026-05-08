"""
Nexus BNL — Security Dashboard
================================
Standalone FastAPI app for the Agent Permission & Security System.

Shows:
  - System-wide security stats
  - Permission catalog grouped by category
  - Active isolated agents
  - Security events (filterable by severity)
  - Policy violations (open)
  - Per-agent risk / threat level
  - Permission audit log

Run:
    uvicorn app.security_dashboard:app --reload --port 8091
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.security_routes import router as security_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus Security Dashboard", docs_url="/api/docs", redoc_url=None)
app.include_router(security_router)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-security"})


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus — Security Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:      #0b0b0f;
    --surface: #111118;
    --border:  #1e1e2a;
    --muted:   #3a3a50;
    --text:    #c9d1d9;
    --dim:     #666;
    --blue:    #58a6ff;
    --green:   #3fb950;
    --yellow:  #e3b341;
    --red:     #f85149;
    --purple:  #bc8cff;
    --cyan:    #39c5cf;
    --orange:  #d4a72c;
    --mono:    'Cascadia Code','Fira Code',Consolas,monospace;
  }
  body { font-family:var(--mono); background:var(--bg); color:var(--text); font-size:13px; min-height:100vh; }

  /* ── Top bar ── */
  #topbar {
    position:sticky; top:0; z-index:100;
    background:var(--surface); border-bottom:1px solid var(--border);
    padding:10px 20px; display:flex; align-items:center; gap:12px;
  }
  .logo { color:var(--red); font-size:15px; font-weight:700; letter-spacing:.04em; }
  .logo-sep { color:var(--muted); }
  .logo-sub { color:var(--dim); font-size:11px; }
  #sync-btn {
    margin-left:auto; padding:4px 14px; font-size:11px; font-family:var(--mono);
    border-radius:4px; border:1px solid var(--muted);
    background:var(--surface); color:#aaa; cursor:pointer;
  }
  #sync-btn:hover { border-color:var(--red); color:var(--red); }
  #last-sync { color:var(--muted); font-size:10px; margin-left:8px; }

  /* ── Content ── */
  #content { padding:20px; max-width:1400px; margin:0 auto; }

  /* ── Stat cards ── */
  #stats-row { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:22px; }
  .stat-card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:12px 14px; }
  .stat-label { font-size:10px; color:var(--dim); text-transform:uppercase; letter-spacing:.06em; }
  .stat-value { font-size:24px; font-weight:700; margin-top:4px; }
  .c-blue   { color:var(--blue); }
  .c-green  { color:var(--green); }
  .c-yellow { color:var(--yellow); }
  .c-red    { color:var(--red); }
  .c-purple { color:var(--purple); }
  .c-cyan   { color:var(--cyan); }
  .c-orange { color:var(--orange); }

  /* ── Sections ── */
  .section { background:var(--surface); border:1px solid var(--border); border-radius:6px; margin-bottom:18px; overflow:hidden; }
  .section-hdr {
    padding:10px 14px; border-bottom:1px solid var(--border);
    display:flex; align-items:center; gap:8px;
    font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--dim);
  }
  .section-hdr .badge { margin-left:auto; background:#1a1a28; border-radius:10px; padding:1px 8px; font-size:11px; color:var(--muted); }
  .section-body { padding:14px; }
  .two-col { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
  @media(max-width:900px){ .two-col { grid-template-columns:1fr; } }

  /* ── Tables ── */
  .data-table { width:100%; border-collapse:collapse; }
  .data-table th { text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); padding:6px 10px; border-bottom:1px solid var(--border); }
  .data-table td { padding:7px 10px; border-bottom:1px solid #161620; font-size:11px; vertical-align:top; }
  .data-table tr:last-child td { border-bottom:none; }
  .data-table tr:hover td { background:#0e0e18; }

  /* ── Pills ── */
  .pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:10px; }
  .pill-info     { background:#0d1a28; color:var(--blue); }
  .pill-warning  { background:#2a200d; color:var(--yellow); }
  .pill-critical { background:#2a0d0d; color:var(--red); }
  .pill-grant    { background:#0d2a15; color:var(--green); }
  .pill-revoke   { background:#2a1a0d; color:var(--orange); }
  .pill-fail     { background:#2a0d0d; color:var(--red); }
  .pill-pass     { background:#0d2015; color:var(--green); }
  .pill-isolated { background:#2a0d0d; color:var(--red); border:1px solid #5a1515; }

  /* ── Risk meter ── */
  .risk-bar { display:inline-block; width:70px; height:5px; border-radius:3px; background:var(--border); position:relative; vertical-align:middle; }
  .risk-fill { position:absolute; left:0; top:0; bottom:0; border-radius:3px; }

  /* ── Permission catalog grid ── */
  #cat-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }
  .cat-group { background:#0e0e16; border:1px solid var(--border); border-radius:5px; padding:12px; }
  .cat-name { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--cyan); margin-bottom:8px; }
  .cat-perm { padding:3px 0; font-size:11px; display:flex; align-items:center; gap:6px; }
  .cat-perm-id { color:var(--purple); }
  .cat-perm-risk { color:var(--dim); font-size:10px; }
  .cat-perm-level { color:var(--yellow); font-size:10px; }

  /* ── Isolated agent cards ── */
  #isolated-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:10px; }
  .iso-card {
    background:#1a0a0a; border:1px solid #5a1515; border-radius:5px; padding:12px;
    border-left:3px solid var(--red);
  }
  .iso-agent { color:var(--red); font-size:12px; font-weight:700; }
  .iso-reason { color:var(--dim); font-size:11px; margin-top:4px; line-height:1.4; }
  .iso-by { color:var(--muted); font-size:10px; margin-top:6px; }
  .iso-time { color:var(--muted); font-size:10px; }

  /* ── Level badge ── */
  .lvl { display:inline-block; padding:1px 7px; border-radius:3px; font-size:10px; font-weight:600; }
  .lvl-NONE     { background:#1a1a28; color:var(--dim); }
  .lvl-LOW      { background:#0d2015; color:var(--green); }
  .lvl-MEDIUM   { background:#2a200d; color:var(--yellow); }
  .lvl-HIGH     { background:#2a1a0d; color:var(--orange); }
  .lvl-CRITICAL { background:#2a0d0d; color:var(--red); }

  /* ── Filter row ── */
  .filter-row { display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
  .filter-btn {
    padding:3px 12px; font-size:10px; font-family:var(--mono); cursor:pointer;
    border-radius:10px; border:1px solid var(--muted);
    background:var(--surface); color:var(--dim); transition:all .1s;
  }
  .filter-btn:hover, .filter-btn.active { border-color:var(--blue); color:var(--blue); background:#0a1a30; }

  /* ── Empty ── */
  .empty { padding:20px; text-align:center; color:var(--muted); font-size:11px; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width:5px; }
  ::-webkit-scrollbar-track { background:var(--bg); }
  ::-webkit-scrollbar-thumb { background:var(--muted); border-radius:2px; }
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">⚔ Nexus</span>
  <span class="logo-sep">|</span>
  <span class="logo-sub">Security Dashboard</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- Stats -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Active Grants</div><div class="stat-value c-blue"  id="s-grants">—</div></div>
    <div class="stat-card"><div class="stat-label">Check Passes</div><div class="stat-value c-green" id="s-pass">—</div></div>
    <div class="stat-card"><div class="stat-label">Check Failures</div><div class="stat-value c-red"  id="s-fail">—</div></div>
    <div class="stat-card"><div class="stat-label">Open Violations</div><div class="stat-value c-orange" id="s-viol">—</div></div>
    <div class="stat-card"><div class="stat-label">Security Events</div><div class="stat-value c-purple" id="s-evts">—</div></div>
    <div class="stat-card"><div class="stat-label">Critical Events</div><div class="stat-value c-red"    id="s-crit">—</div></div>
    <div class="stat-card"><div class="stat-label">Isolated Agents</div><div class="stat-value c-red"    id="s-iso">—</div></div>
    <div class="stat-card"><div class="stat-label">Revoked Grants</div><div class="stat-value c-yellow"  id="s-revoked">—</div></div>
  </div>

  <!-- Isolated agents -->
  <div class="section">
    <div class="section-hdr" style="border-left:3px solid var(--red)">
      ⚠ Isolated Agents
      <span class="badge" id="iso-badge">0</span>
    </div>
    <div class="section-body">
      <div id="isolated-grid"><div class="empty">No isolated agents — system healthy</div></div>
    </div>
  </div>

  <div class="two-col">

    <!-- Security events -->
    <div class="section">
      <div class="section-hdr">
        ▪ Security Events
        <span class="badge" id="events-badge">0</span>
      </div>
      <div class="section-body" style="padding:8px 14px">
        <div class="filter-row" id="event-filters">
          <button class="filter-btn active" data-sev="" onclick="filterEvents(this,'')">All</button>
          <button class="filter-btn" data-sev="CRITICAL" onclick="filterEvents(this,'CRITICAL')">Critical</button>
          <button class="filter-btn" data-sev="WARNING"  onclick="filterEvents(this,'WARNING')">Warning</button>
          <button class="filter-btn" data-sev="INFO"     onclick="filterEvents(this,'INFO')">Info</button>
        </div>
      </div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Agent</th><th>Type</th><th>Severity</th></tr></thead>
          <tbody id="events-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Violations -->
    <div class="section">
      <div class="section-hdr">
        ▪ Policy Violations
        <span class="badge" id="violations-badge">0</span>
      </div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Agent</th><th>Type</th><th>Permission</th></tr></thead>
          <tbody id="violations-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Permission catalog -->
  <div class="section">
    <div class="section-hdr">
      ▪ Permission Catalog
      <span class="badge" id="catalog-badge">0</span>
    </div>
    <div class="section-body">
      <div id="cat-grid"><div class="empty">Loading…</div></div>
    </div>
  </div>

  <!-- Audit log -->
  <div class="section">
    <div class="section-hdr">
      ▪ Audit Log
      <span class="badge" id="log-badge">0</span>
    </div>
    <div style="padding:0">
      <table class="data-table">
        <thead><tr><th>Time</th><th>Agent</th><th>Permission</th><th>Action</th><th>By</th></tr></thead>
        <tbody id="log-body"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

</div><!-- /content -->

<script>
// ── State ──────────────────────────────────────────────────────────────────────
let _allEvents = [];
let _evtFilter = '';

// ── Helpers ────────────────────────────────────────────────────────────────────
async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function ts(s){ return s ? s.replace('T',' ').replace('Z','') : '—'; }

function sevPill(sev){
  const m = {CRITICAL:'critical', WARNING:'warning', INFO:'info'};
  return `<span class="pill pill-${m[sev]||'info'}">${esc(sev||'INFO')}</span>`;
}
function actionPill(a){
  const m = {GRANT:'grant', REVOKE:'revoke', CHECK_FAIL:'fail', CHECK_PASS:'pass'};
  return `<span class="pill pill-${m[a]||'info'}">${esc(a)}</span>`;
}
function riskFill(score){
  const color = score>=80?'var(--red)': score>=50?'var(--orange)': score>=20?'var(--yellow)':'var(--green)';
  return `<span class="risk-bar"><span class="risk-fill" style="width:${score}%;background:${color}"></span></span>`;
}

// ── Stats ──────────────────────────────────────────────────────────────────────
function renderStats(s){
  document.getElementById('s-grants').textContent  = s.active_grants    ?? '—';
  document.getElementById('s-pass').textContent    = s.check_passes     ?? '—';
  document.getElementById('s-fail').textContent    = s.check_failures   ?? '—';
  document.getElementById('s-viol').textContent    = s.open_violations  ?? '—';
  document.getElementById('s-evts').textContent    = s.security_events  ?? '—';
  document.getElementById('s-crit').textContent    = s.critical_events  ?? '—';
  document.getElementById('s-iso').textContent     = s.isolated_agents  ?? '—';
  document.getElementById('s-revoked').textContent = s.revoked_grants   ?? '—';
}

// ── Isolated ───────────────────────────────────────────────────────────────────
function renderIsolated(agents){
  const grid = document.getElementById('isolated-grid');
  document.getElementById('iso-badge').textContent = agents.length;
  if(!agents.length){
    grid.innerHTML = '<div class="empty" style="color:var(--green)">✓ No isolated agents — system healthy</div>';
    return;
  }
  grid.innerHTML = agents.map(a=>`
    <div class="iso-card">
      <div class="iso-agent">⚠ ${esc(a.agent_id)}</div>
      <div class="iso-reason">${esc(a.reason)}</div>
      <div class="iso-by">by ${esc(a.isolated_by||'system')}</div>
      <div class="iso-time">${ts(a.isolated_at)}</div>
    </div>
  `).join('');
}

// ── Events ─────────────────────────────────────────────────────────────────────
function filterEvents(btn, sev){
  document.querySelectorAll('#event-filters .filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  _evtFilter = sev;
  renderEvents(_allEvents);
}

function renderEvents(events){
  const tbody = document.getElementById('events-body');
  const filtered = _evtFilter ? events.filter(e=>e.severity===_evtFilter) : events;
  document.getElementById('events-badge').textContent = filtered.length;
  if(!filtered.length){ tbody.innerHTML='<tr><td colspan="4" class="empty">No events</td></tr>'; return; }
  tbody.innerHTML = filtered.slice(0,50).map(e=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(e.timestamp)}</td>
    <td style="color:var(--blue)">${esc(e.agent_id||'system')}</td>
    <td style="color:var(--text)">${esc(e.event_type)}</td>
    <td>${sevPill(e.severity)}</td>
  </tr>`).join('');
}

// ── Violations ─────────────────────────────────────────────────────────────────
function renderViolations(violations){
  const tbody = document.getElementById('violations-body');
  document.getElementById('violations-badge').textContent = violations.length;
  if(!violations.length){ tbody.innerHTML='<tr><td colspan="4" class="empty">No open violations</td></tr>'; return; }
  tbody.innerHTML = violations.slice(0,50).map(v=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(v.timestamp)}</td>
    <td style="color:var(--red)">${esc(v.agent_id)}</td>
    <td style="color:var(--orange)">${esc(v.violation_type)}</td>
    <td style="color:var(--purple);font-size:10px">${esc(v.permission_id)}</td>
  </tr>`).join('');
}

// ── Catalog ────────────────────────────────────────────────────────────────────
function renderCatalog(catalog){
  const grid = document.getElementById('cat-grid');
  document.getElementById('catalog-badge').textContent = catalog.length;
  const groups = {};
  catalog.forEach(p=>{ (groups[p.category]=groups[p.category]||[]).push(p); });
  const cats = Object.keys(groups).sort();
  if(!cats.length){ grid.innerHTML='<div class="empty">Empty catalog</div>'; return; }
  grid.innerHTML = cats.map(cat=>`
    <div class="cat-group">
      <div class="cat-name">${esc(cat)}</div>
      ${groups[cat].map(p=>`
        <div class="cat-perm">
          <span class="cat-perm-id">${esc(p.permission_id)}</span>
          <span class="cat-perm-level">[${esc(p.min_level)}]</span>
          <span class="cat-perm-risk">r:${p.risk_score}</span>
        </div>
      `).join('')}
    </div>
  `).join('');
}

// ── Audit log ──────────────────────────────────────────────────────────────────
function renderLogs(logs){
  const tbody = document.getElementById('log-body');
  document.getElementById('log-badge').textContent = logs.length;
  if(!logs.length){ tbody.innerHTML='<tr><td colspan="5" class="empty">No logs</td></tr>'; return; }
  tbody.innerHTML = logs.slice(0,100).map(l=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(l.timestamp)}</td>
    <td style="color:var(--blue);font-size:11px">${esc(l.agent_id)}</td>
    <td style="color:var(--purple);font-size:10px">${esc(l.permission_id)}</td>
    <td>${actionPill(l.action)}</td>
    <td style="color:var(--dim);font-size:10px">${esc(l.performed_by||'system')}</td>
  </tr>`).join('');
}

// ── Load all ───────────────────────────────────────────────────────────────────
async function loadAll(){
  document.getElementById('last-sync').textContent = 'syncing…';
  try {
    const [statsR, isoR, evtsR, violsR, catR, logsR] = await Promise.all([
      get('/security/status'),
      get('/security/isolated'),
      get('/security/events?limit=200'),
      get('/security/violations?limit=100'),
      get('/security/catalog'),
      get('/security/logs?limit=200'),
    ]);
    renderStats(statsR.stats||{});
    renderIsolated(isoR.isolated_agents||[]);
    _allEvents = evtsR.events||[];
    renderEvents(_allEvents);
    renderViolations(violsR.violations||[]);
    renderCatalog(catR.catalog||[]);
    renderLogs(logsR.logs||[]);
    document.getElementById('last-sync').textContent = 'synced ' + new Date().toLocaleTimeString();
  } catch(e){
    console.error('loadAll', e);
    document.getElementById('last-sync').textContent = 'error: ' + e.message;
  }
}

loadAll();
setInterval(loadAll, 8000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.security_dashboard:app", host="0.0.0.0", port=8091, reload=True)
