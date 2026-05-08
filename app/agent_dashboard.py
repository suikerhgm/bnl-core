"""
Nexus BNL — Agent Registry Dashboard
======================================
Standalone FastAPI app with a dark-themed HTML dashboard for the Agent Registry.

Shows:
  - Registry stats (totals, active, temporary)
  - Department overview with agent counts
  - Active permanent agents
  - Active temporary agents
  - Parent → child hierarchy tree
  - Capability catalog by category

Run:
    uvicorn app.agent_dashboard:app --reload --port 8090
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.agent_routes import router as agents_router
from core.agents.nexus_registry import get_registry

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus Agent Registry", docs_url="/api/docs", redoc_url=None)
app.include_router(agents_router)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-agent-registry"})


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus — Agent Registry</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0b0b0f;
    --surface:  #111118;
    --border:   #1e1e2a;
    --muted:    #3a3a50;
    --text:     #c9d1d9;
    --dim:      #666;
    --blue:     #58a6ff;
    --green:    #3fb950;
    --yellow:   #e3b341;
    --red:      #f85149;
    --purple:   #bc8cff;
    --cyan:     #39c5cf;
    --orange:   #d4a72c;
    --mono:     'Cascadia Code', 'Fira Code', Consolas, monospace;
  }

  body {
    font-family: var(--mono);
    background: var(--bg);
    color: var(--text);
    font-size: 13px;
    min-height: 100vh;
  }

  /* ── Top bar ── */
  #topbar {
    position: sticky; top: 0; z-index: 100;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 10px 20px;
    display: flex; align-items: center; gap: 12px;
  }
  .logo { color: var(--blue); font-size: 15px; font-weight: 700; letter-spacing: .04em; }
  .logo-sep { color: var(--muted); }
  .logo-sub { color: var(--dim); font-size: 11px; }
  #sync-btn {
    margin-left: auto;
    padding: 4px 14px; font-size: 11px; font-family: var(--mono);
    border-radius: 4px; border: 1px solid var(--muted);
    background: var(--surface); color: #aaa; cursor: pointer;
  }
  #sync-btn:hover { border-color: var(--blue); color: var(--blue); }
  #last-sync { color: var(--muted); font-size: 10px; margin-left: 8px; }

  /* ── Layout ── */
  #content { padding: 20px; max-width: 1400px; margin: 0 auto; }

  /* ── Stat cards ── */
  #stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 22px;
  }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 14px;
  }
  .stat-label { font-size: 10px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }
  .stat-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
  .stat-value.blue   { color: var(--blue); }
  .stat-value.green  { color: var(--green); }
  .stat-value.yellow { color: var(--yellow); }
  .stat-value.red    { color: var(--red); }
  .stat-value.purple { color: var(--purple); }
  .stat-value.cyan   { color: var(--cyan); }

  /* ── Sections ── */
  .section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 18px;
    overflow: hidden;
  }
  .section-hdr {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: var(--dim);
  }
  .section-hdr .badge {
    margin-left: auto;
    background: #1a1a28; border-radius: 10px;
    padding: 1px 8px; font-size: 11px; color: var(--muted);
  }
  .section-body { padding: 14px; }

  /* ── Two-column grid ── */
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

  /* ── Department cards ── */
  #dept-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 10px;
  }
  .dept-card {
    background: #0e0e16;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 12px;
    transition: border-color .15s;
  }
  .dept-card:hover { border-color: var(--blue); }
  .dept-icon { font-size: 18px; }
  .dept-name { font-size: 12px; color: var(--text); margin-top: 6px; font-weight: 600; }
  .dept-desc { font-size: 10px; color: var(--dim); margin-top: 3px; line-height: 1.4; }
  .dept-count {
    margin-top: 8px; display: inline-block;
    background: #1a1a28; border-radius: 10px;
    padding: 1px 8px; font-size: 11px; color: var(--blue);
  }

  /* ── Agent table ── */
  .agent-table { width: 100%; border-collapse: collapse; }
  .agent-table th {
    text-align: left; font-size: 10px; text-transform: uppercase;
    letter-spacing: .06em; color: var(--muted);
    padding: 6px 10px; border-bottom: 1px solid var(--border);
  }
  .agent-table td {
    padding: 8px 10px; border-bottom: 1px solid #161620;
    font-size: 12px; vertical-align: middle;
  }
  .agent-table tr:last-child td { border-bottom: none; }
  .agent-table tr:hover td { background: #0e0e18; }

  .pill {
    display: inline-block; padding: 1px 8px;
    border-radius: 10px; font-size: 10px;
  }
  .pill-active   { background: #0d2a15; color: var(--green); }
  .pill-inactive { background: #1a1a28; color: var(--muted); }
  .pill-terminated { background: #2a0d0d; color: var(--red); }
  .pill-temp     { background: #2a1f0d; color: var(--orange); }

  .trust-bar {
    display: inline-block;
    width: 50px; height: 5px; border-radius: 3px;
    background: var(--border); position: relative; vertical-align: middle;
  }
  .trust-fill {
    position: absolute; left: 0; top: 0; bottom: 0;
    border-radius: 3px; background: var(--blue);
  }

  .cap-tag {
    display: inline-block; margin: 1px 2px;
    padding: 1px 7px; border-radius: 10px;
    font-size: 10px; background: #1a1a30; color: var(--purple);
    border: 1px solid #2a2a48;
  }

  /* ── Hierarchy tree ── */
  .tree-node { padding: 6px 0; }
  .tree-parent {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; border-radius: 4px;
    background: #0e0e18; border: 1px solid var(--border);
    margin-bottom: 4px;
  }
  .tree-children { margin-left: 24px; border-left: 1px solid var(--border); padding-left: 14px; }
  .tree-child {
    display: flex; align-items: center; gap: 8px;
    padding: 4px 8px; border-radius: 3px;
    background: #090911; border: 1px solid #181826;
    margin-top: 4px; font-size: 11px;
  }
  .tree-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dot-active { background: var(--green); }
  .dot-inactive { background: var(--muted); }
  .dot-terminated { background: var(--red); }
  .dot-temporary { background: var(--orange); }

  /* ── Capabilities ── */
  #cap-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 14px;
  }
  .cap-category {
    background: #0e0e16;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 12px;
  }
  .cap-cat-name {
    font-size: 10px; text-transform: uppercase;
    letter-spacing: .06em; color: var(--cyan); margin-bottom: 8px;
  }
  .cap-item {
    padding: 3px 0; font-size: 11px; color: var(--dim);
    display: flex; align-items: center; gap: 6px;
  }
  .cap-item::before { content: '›'; color: var(--purple); }

  /* ── Empty state ── */
  .empty { padding: 24px; text-align: center; color: var(--muted); font-size: 12px; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 2px; }
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">◈ Nexus</span>
  <span class="logo-sep">|</span>
  <span class="logo-sub">Agent Registry</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- Stats row -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Total Agents</div><div class="stat-value blue" id="s-total">—</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value green" id="s-active">—</div></div>
    <div class="stat-card"><div class="stat-label">Inactive</div><div class="stat-value yellow" id="s-inactive">—</div></div>
    <div class="stat-card"><div class="stat-label">Temporary</div><div class="stat-value purple" id="s-temp">—</div></div>
    <div class="stat-card"><div class="stat-label">Terminated</div><div class="stat-value red" id="s-term">—</div></div>
    <div class="stat-card"><div class="stat-label">Departments</div><div class="stat-value cyan" id="s-depts">—</div></div>
    <div class="stat-card"><div class="stat-label">Capabilities</div><div class="stat-value blue" id="s-caps">—</div></div>
    <div class="stat-card"><div class="stat-label">Contracts</div><div class="stat-value yellow" id="s-contracts">—</div></div>
  </div>

  <!-- Departments -->
  <div class="section">
    <div class="section-hdr">
      ▪ Departments
      <span class="badge" id="depts-badge">0</span>
    </div>
    <div class="section-body">
      <div id="dept-grid"><div class="empty">Loading…</div></div>
    </div>
  </div>

  <div class="two-col">

    <!-- Active agents -->
    <div class="section">
      <div class="section-hdr">
        ▪ Active Agents
        <span class="badge" id="active-badge">0</span>
      </div>
      <div class="section-body" style="padding:0">
        <table class="agent-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Dept</th>
              <th>Trust</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="active-agents-body">
            <tr><td colspan="5" class="empty">Loading…</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Temporary agents -->
    <div class="section">
      <div class="section-hdr">
        ▪ Temporary Agents
        <span class="badge" id="temp-badge">0</span>
      </div>
      <div class="section-body" style="padding:0">
        <table class="agent-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Dept</th>
              <th>Trust</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="temp-agents-body">
            <tr><td colspan="5" class="empty">Loading…</td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Hierarchy -->
  <div class="section">
    <div class="section-hdr">▪ Agent Hierarchy</div>
    <div class="section-body" id="hierarchy-body">
      <div class="empty">Loading…</div>
    </div>
  </div>

  <!-- Capabilities -->
  <div class="section">
    <div class="section-hdr">
      ▪ Capability Catalog
      <span class="badge" id="caps-badge">0</span>
    </div>
    <div class="section-body">
      <div id="cap-grid"><div class="empty">Loading…</div></div>
    </div>
  </div>

</div><!-- /content -->

<script>
const BASE = '';  // same origin

// ── Dept icons ─────────────────────────────────────────────────────────────────
const DEPT_ICONS = {
  engineering: '⚙️', frontend: '🎨', security: '🔐',
  runtime: '⚡', repairs: '🔧', research: '🔬',
  media: '🎬', gaming: '🎮',
};

// ── Fetch helpers ──────────────────────────────────────────────────────────────
async function get(url) {
  const res = await fetch(BASE + url);
  if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + url);
  return res.json();
}

// ── Render stats ───────────────────────────────────────────────────────────────
function renderStats(s) {
  document.getElementById('s-total').textContent     = s.total_agents      ?? '—';
  document.getElementById('s-active').textContent    = s.active_agents     ?? '—';
  document.getElementById('s-inactive').textContent  = s.inactive_agents   ?? '—';
  document.getElementById('s-temp').textContent      = s.active_temporary  ?? '—';
  document.getElementById('s-term').textContent      = s.terminated_agents ?? '—';
  document.getElementById('s-depts').textContent     = s.departments       ?? '—';
  document.getElementById('s-caps').textContent      = s.capabilities      ?? '—';
  document.getElementById('s-contracts').textContent = s.active_contracts  ?? '—';
}

// ── Render departments ─────────────────────────────────────────────────────────
function renderDepts(depts) {
  const grid = document.getElementById('dept-grid');
  document.getElementById('depts-badge').textContent = depts.length;
  if (!depts.length) { grid.innerHTML = '<div class="empty">No departments</div>'; return; }
  grid.innerHTML = depts.map(d => `
    <div class="dept-card">
      <div class="dept-icon">${DEPT_ICONS[d.department_id] || '🏢'}</div>
      <div class="dept-name">${esc(d.name)}</div>
      <div class="dept-desc">${esc(d.description || '')}</div>
      <span class="dept-count">${d.agent_count} agents</span>
    </div>
  `).join('');
}

// ── Render agent table rows ────────────────────────────────────────────────────
function agentRow(a) {
  const statusCls = {active:'pill-active', inactive:'pill-inactive', terminated:'pill-terminated'}[a.status] || 'pill-inactive';
  const trust = Math.max(0, Math.min(100, a.trust_level || 0));
  return `<tr>
    <td>${esc(a.name)}</td>
    <td style="color:var(--dim)">${esc(a.role)}</td>
    <td style="color:var(--cyan)">${esc(a.department || '—')}</td>
    <td>
      <span class="trust-bar"><span class="trust-fill" style="width:${trust}%"></span></span>
      <span style="margin-left:5px;color:var(--dim);font-size:10px">${trust}</span>
    </td>
    <td><span class="pill ${statusCls}">${esc(a.status)}</span>${a.temporary ? ' <span class="pill pill-temp">temp</span>' : ''}</td>
  </tr>`;
}

function renderAgentTable(tbodyId, badgeId, agents) {
  const tbody = document.getElementById(tbodyId);
  document.getElementById(badgeId).textContent = agents.length;
  if (!agents.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No agents</td></tr>';
    return;
  }
  tbody.innerHTML = agents.map(agentRow).join('');
}

// ── Render hierarchy ───────────────────────────────────────────────────────────
function dotCls(a) {
  if (a.temporary) return 'dot-temporary';
  return 'dot-' + (a.status || 'inactive');
}

function renderHierarchy(agents) {
  const body = document.getElementById('hierarchy-body');
  const roots = agents.filter(a => !a.parent_agent);
  const byParent = {};
  agents.forEach(a => {
    if (a.parent_agent) {
      (byParent[a.parent_agent] = byParent[a.parent_agent] || []).push(a);
    }
  });

  if (!roots.length) {
    body.innerHTML = '<div class="empty">No agents registered yet</div>';
    return;
  }

  function renderNode(a, depth) {
    const children = byParent[a.agent_id] || [];
    const childrenHtml = children.length
      ? `<div class="tree-children">${children.map(c => renderNode(c, depth + 1)).join('')}</div>`
      : '';
    const cls = depth === 0 ? 'tree-parent' : 'tree-child';
    return `
      <div class="tree-node">
        <div class="${cls}">
          <span class="tree-dot ${dotCls(a)}"></span>
          <span style="color:var(--text)">${esc(a.name)}</span>
          <span style="color:var(--dim);font-size:10px">${esc(a.role)}</span>
          ${a.department ? `<span style="color:var(--cyan);font-size:10px">[${esc(a.department)}]</span>` : ''}
          ${a.temporary ? '<span class="pill pill-temp" style="font-size:9px">temp</span>' : ''}
        </div>
        ${childrenHtml}
      </div>`;
  }

  body.innerHTML = roots.map(r => renderNode(r, 0)).join('');
}

// ── Render capabilities ────────────────────────────────────────────────────────
function renderCaps(data) {
  const grid = document.getElementById('cap-grid');
  document.getElementById('caps-badge').textContent = data.count || 0;
  const bycat = data.by_category || {};
  const cats = Object.keys(bycat).sort();
  if (!cats.length) { grid.innerHTML = '<div class="empty">No capabilities</div>'; return; }
  grid.innerHTML = cats.map(cat => `
    <div class="cap-category">
      <div class="cap-cat-name">${esc(cat)}</div>
      ${bycat[cat].map(c => `<div class="cap-item">${esc(c.name)}</div>`).join('')}
    </div>
  `).join('');
}

// ── Escape ─────────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Load all ───────────────────────────────────────────────────────────────────
async function loadAll() {
  document.getElementById('last-sync').textContent = 'syncing…';
  try {
    const [statsRes, deptsRes, agentsRes, capsRes] = await Promise.all([
      get('/agents/status'),
      get('/agents/departments'),
      get('/agents/list'),
      get('/agents/capabilities'),
    ]);

    renderStats(statsRes.stats || {});
    renderDepts(deptsRes.departments || []);

    const all       = agentsRes.agents || [];
    const permanent = all.filter(a => !a.temporary);
    const temporary = all.filter(a => a.temporary);

    renderAgentTable('active-agents-body', 'active-badge', permanent);
    renderAgentTable('temp-agents-body', 'temp-badge', temporary);
    renderHierarchy(all);
    renderCaps(capsRes);

    document.getElementById('last-sync').textContent = 'synced ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error('loadAll error', e);
    document.getElementById('last-sync').textContent = 'error: ' + e.message;
  }
}

loadAll();
setInterval(loadAll, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the Agent Registry dashboard."""
    return HTMLResponse(_DASHBOARD_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.agent_dashboard:app", host="0.0.0.0", port=8090, reload=True)
