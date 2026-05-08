"""
Nexus BNL — Isolation Dashboard
=================================
Standalone FastAPI app for the Runtime Isolation System.

Shows:
  - System stats (active / frozen / quarantined / lockdown state)
  - Live isolated process list with risk scores
  - Per-process CPU / RAM bar charts
  - Runtime violations log
  - Emergency events (KILL / QUARANTINE / LOCKDOWN)
  - Isolation level profiles reference

Run:
    uvicorn app.isolation_dashboard:app --reload --port 8093
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.isolation_routes import router as isolation_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus Isolation Dashboard", docs_url="/api/docs", redoc_url=None)
app.include_router(isolation_router)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-isolation"})


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus — Isolation Dashboard</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0b0b0f; --surface:#111118; --border:#1e1e2a; --muted:#3a3a50;
    --text:#c9d1d9; --dim:#666;
    --blue:#58a6ff; --green:#3fb950; --yellow:#e3b341;
    --red:#f85149; --purple:#bc8cff; --cyan:#39c5cf;
    --orange:#d4a72c; --mono:'Cascadia Code','Fira Code',Consolas,monospace;
  }
  body{font-family:var(--mono);background:var(--bg);color:var(--text);font-size:13px;min-height:100vh}

  #topbar{
    position:sticky;top:0;z-index:100;background:var(--surface);
    border-bottom:1px solid var(--border);padding:10px 20px;
    display:flex;align-items:center;gap:12px;
  }
  .logo{color:var(--cyan);font-size:15px;font-weight:700;letter-spacing:.04em}
  .logo-sub{color:var(--dim);font-size:11px}
  .lockdown-badge{
    padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;
    background:#2a0d0d;color:var(--red);border:1px solid #5a1515;
    display:none;animation:pulse 1s infinite;
  }
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
  #sync-btn{
    margin-left:auto;padding:4px 14px;font-size:11px;font-family:var(--mono);
    border-radius:4px;border:1px solid var(--muted);background:var(--surface);
    color:#aaa;cursor:pointer;
  }
  #sync-btn:hover{border-color:var(--cyan);color:var(--cyan)}
  #last-sync{color:var(--muted);font-size:10px;margin-left:8px}

  #content{padding:20px;max-width:1400px;margin:0 auto}

  /* Stats */
  #stats-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:22px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:12px 14px}
  .stat-label{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
  .stat-value{font-size:24px;font-weight:700;margin-top:4px}
  .c-blue{color:var(--blue)}.c-green{color:var(--green)}.c-yellow{color:var(--yellow)}
  .c-red{color:var(--red)}.c-purple{color:var(--purple)}.c-cyan{color:var(--cyan)}
  .c-orange{color:var(--orange)}

  /* Sections */
  .section{background:var(--surface);border:1px solid var(--border);border-radius:6px;margin-bottom:18px;overflow:hidden}
  .section-hdr{
    padding:10px 14px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;gap:8px;
    font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
  }
  .section-hdr .badge{margin-left:auto;background:#1a1a28;border-radius:10px;padding:1px 8px;font-size:11px;color:var(--muted)}
  .section-body{padding:14px}
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:900px){.two-col{grid-template-columns:1fr}}

  /* Process cards */
  #proc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
  .proc-card{
    background:#0e0e16;border:1px solid var(--border);border-radius:5px;padding:14px;
    cursor:pointer;transition:border-color .15s;
  }
  .proc-card:hover{border-color:var(--cyan)}
  .proc-card.frozen     {border-left:3px solid var(--cyan)}
  .proc-card.quarantined{border-left:3px solid var(--red);background:#1a0a0a}
  .proc-card.active     {border-left:3px solid var(--green)}
  .proc-pid{font-size:10px;color:var(--dim)}
  .proc-level{font-size:11px;margin-top:3px}
  .proc-agent{font-size:11px;color:var(--purple)}
  .proc-metrics{margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:4px}
  .metric-row{display:flex;justify-content:space-between;font-size:10px}
  .metric-key{color:var(--dim)}
  .metric-val{color:var(--text)}

  /* Resource bar */
  .res-bar{display:inline-block;height:4px;border-radius:2px;background:var(--border);position:relative;vertical-align:middle;width:100%}
  .res-fill{position:absolute;left:0;top:0;bottom:0;border-radius:2px}

  /* Pills */
  .pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px}
  .pill-active     {background:#0d2a15;color:var(--green)}
  .pill-frozen     {background:#0d2228;color:var(--cyan)}
  .pill-quarantined{background:#2a0d0d;color:var(--red);border:1px solid #5a1515}
  .pill-destroyed  {background:#1a1a1a;color:#333}
  .pill-responding {background:#2a1a0d;color:var(--orange)}

  /* Level colors */
  .lvl-SOFT       {color:var(--green)}
  .lvl-RESTRICTED {color:var(--blue)}
  .lvl-HARD       {color:var(--yellow)}
  .lvl-QUARANTINE {color:var(--orange)}
  .lvl-LOCKDOWN   {color:var(--red)}

  /* Tables */
  .data-table{width:100%;border-collapse:collapse}
  .data-table th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:6px 10px;border-bottom:1px solid var(--border)}
  .data-table td{padding:7px 10px;border-bottom:1px solid #161620;font-size:11px;vertical-align:top;word-break:break-word}
  .data-table tr:last-child td{border-bottom:none}
  .data-table tr:hover td{background:#0e0e18}

  /* Level profiles */
  #level-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
  .level-card{background:#0e0e16;border:1px solid var(--border);border-radius:5px;padding:12px}
  .level-name{font-size:11px;font-weight:700;margin-bottom:8px}
  .level-row{display:flex;justify-content:space-between;font-size:10px;padding:2px 0}
  .level-key{color:var(--dim)}
  .level-val{color:var(--text)}

  /* Empty */
  .empty{padding:20px;text-align:center;color:var(--muted);font-size:11px}
  ::-webkit-scrollbar{width:5px}
  ::-webkit-scrollbar-track{background:var(--bg)}
  ::-webkit-scrollbar-thumb{background:var(--muted);border-radius:2px}
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">⬡ Nexus</span>
  <span style="color:var(--muted)">|</span>
  <span class="logo-sub">Runtime Isolation</span>
  <span class="lockdown-badge" id="lockdown-badge">⚠ LOCKDOWN ACTIVE</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- Stats -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Total Isolated</div><div class="stat-value c-blue"   id="s-total">—</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value c-green"  id="s-active">—</div></div>
    <div class="stat-card"><div class="stat-label">Frozen</div><div class="stat-value c-cyan"   id="s-frozen">—</div></div>
    <div class="stat-card"><div class="stat-label">Quarantined</div><div class="stat-value c-red"    id="s-quar">—</div></div>
    <div class="stat-card"><div class="stat-label">Monitored</div><div class="stat-value c-purple" id="s-mon">—</div></div>
    <div class="stat-card"><div class="stat-label">Violations</div><div class="stat-value c-orange" id="s-viols">—</div></div>
    <div class="stat-card"><div class="stat-label">Critical Events</div><div class="stat-value c-red"   id="s-crit">—</div></div>
    <div class="stat-card"><div class="stat-label">Guardian</div><div class="stat-value c-green"  id="s-guard">—</div></div>
  </div>

  <!-- Isolated processes -->
  <div class="section">
    <div class="section-hdr">▪ Isolated Processes <span class="badge" id="proc-badge">0</span></div>
    <div class="section-body">
      <div id="proc-grid"><div class="empty">No isolated processes</div></div>
    </div>
  </div>

  <div class="two-col">

    <!-- Violations -->
    <div class="section">
      <div class="section-hdr">▪ Runtime Violations <span class="badge" id="viol-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Process</th><th>Type</th><th>+Risk</th></tr></thead>
          <tbody id="viol-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Emergency events -->
    <div class="section">
      <div class="section-hdr">▪ Emergency Events <span class="badge" id="emerg-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Action</th><th>Process</th><th>Sev</th></tr></thead>
          <tbody id="emerg-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Isolation level profiles -->
  <div class="section">
    <div class="section-hdr">▪ Isolation Level Profiles</div>
    <div class="section-body"><div id="level-grid"><div class="empty">Loading…</div></div></div>
  </div>

</div>

<script>
async function get(url){const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function ts(s){return s?s.replace('T',' ').replace('Z',''):'—'}
function statusPill(s){return `<span class="pill pill-${s||'active'}">${esc(s||'active')}</span>`}
function sevStyle(s){return s==='CRITICAL'?'color:var(--red)':s==='WARNING'?'color:var(--yellow)':'color:var(--blue)'}
function riskColor(r){return r>=80?'var(--red)':r>=50?'var(--orange)':r>=20?'var(--yellow)':'var(--green)'}

function renderStats(s){
  document.getElementById('s-total').textContent  = s.total_isolated     ??'—';
  document.getElementById('s-active').textContent = s.active             ??'—';
  document.getElementById('s-frozen').textContent = s.frozen             ??'—';
  document.getElementById('s-quar').textContent   = s.quarantined        ??'—';
  document.getElementById('s-mon').textContent    = s.monitored_contexts ??'—';
  document.getElementById('s-viols').textContent  = s.total_violations   ??'—';
  document.getElementById('s-crit').textContent   = s.critical_events    ??'—';
  document.getElementById('s-guard').textContent  = s.guardian_active?'ON':'OFF';
  document.getElementById('s-guard').style.color  = s.guardian_active?'var(--green)':'var(--red)';
  const lb = document.getElementById('lockdown-badge');
  lb.style.display = s.lockdown_active?'inline-block':'none';
}

function metricBar(val,limit,color){
  const pct = limit>0?Math.min(100,(val/limit)*100):0;
  return `<div class="res-bar"><div class="res-fill" style="width:${pct}%;background:${color}"></div></div>`;
}

function renderProcesses(procs){
  const grid = document.getElementById('proc-grid');
  document.getElementById('proc-badge').textContent = procs.length;
  if(!procs.length){grid.innerHTML='<div class="empty">No isolated processes</div>';return}
  grid.innerHTML = procs.map(p=>{
    const risk = p.risk_score||0;
    const rc   = riskColor(risk);
    return `<div class="proc-card ${p.status||'active'}" onclick="alert('process_id: '+${JSON.stringify(p.process_id)})">
      <div style="display:flex;justify-content:space-between;align-items:center">
        ${statusPill(p.status)}
        <span class="lvl-${p.level||'RESTRICTED'}" style="font-size:11px;font-weight:700">${esc(p.level)}</span>
      </div>
      <div class="proc-pid">PID: ${p.pid||'—'}</div>
      ${p.agent_id?`<div class="proc-agent">${esc(p.agent_id)}</div>`:''}
      <div style="margin-top:8px;display:flex;align-items:center;gap:8px">
        <span style="font-size:10px;color:var(--dim)">Risk</span>
        <div style="flex:1">${metricBar(risk,100,rc)}</div>
        <span style="font-size:11px;color:${rc};font-weight:700">${risk}</span>
      </div>
      <div class="proc-metrics">
        <div class="metric-row"><span class="metric-key">CPU lim</span><span class="metric-val">${p.cpu_limit}%</span></div>
        <div class="metric-row"><span class="metric-key">RAM lim</span><span class="metric-val">${p.memory_limit}MB</span></div>
        <div class="metric-row"><span class="metric-key">Procs</span><span class="metric-val">max ${p.max_subprocesses}</span></div>
        <div class="metric-row"><span class="metric-key">Writes</span><span class="metric-val">max ${p.max_file_writes}</span></div>
      </div>
      <div style="font-size:10px;color:var(--dim);margin-top:8px">${ts(p.created_at)}</div>
    </div>`;
  }).join('');
}

function renderViolations(viols){
  const tbody = document.getElementById('viol-body');
  document.getElementById('viol-badge').textContent = viols.length;
  if(!viols.length){tbody.innerHTML='<tr><td colspan="4" class="empty">No violations</td></tr>';return}
  tbody.innerHTML = viols.slice(0,60).map(v=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(v.timestamp)}</td>
    <td style="color:var(--blue);font-size:10px">${esc((v.process_id||'').slice(0,8))}</td>
    <td style="color:var(--orange)">${esc(v.violation_type)}</td>
    <td style="color:var(--red);font-weight:700">+${v.risk_delta||0}</td>
  </tr>`).join('');
}

function renderEmergency(events){
  const tbody = document.getElementById('emerg-body');
  document.getElementById('emerg-badge').textContent = events.length;
  if(!events.length){tbody.innerHTML='<tr><td colspan="4" class="empty">No emergency events</td></tr>';return}
  tbody.innerHTML = events.slice(0,40).map(e=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(e.timestamp)}</td>
    <td style="${sevStyle(e.severity)};font-weight:700">${esc(e.action)}</td>
    <td style="color:var(--blue);font-size:10px">${esc((e.process_id||'').slice(0,8))}</td>
    <td style="${sevStyle(e.severity)}">${esc(e.severity)}</td>
  </tr>`).join('');
}

function renderLevels(levels){
  const grid = document.getElementById('level-grid');
  const keys = {
    cpu_limit_percent:'CPU Limit %',memory_limit_mb:'RAM MB',
    max_subprocesses:'Max Procs',max_file_writes:'Max Writes',
    max_net_connections:'Max Conns',cpu_kill_sustained_sec:'Kill Sec',
    auto_kill:'Auto Kill',auto_quarantine:'Auto Quarantine',
  };
  const colors = {SOFT:'var(--green)',RESTRICTED:'var(--blue)',HARD:'var(--yellow)',QUARANTINE:'var(--orange)',LOCKDOWN:'var(--red)'};
  grid.innerHTML = Object.entries(levels).map(([name,lim])=>`
    <div class="level-card" style="border-left:3px solid ${colors[name]||'var(--muted)'}">
      <div class="level-name" style="color:${colors[name]||'var(--text)'}">${esc(name)}</div>
      ${Object.entries(keys).map(([k,label])=>
        `<div class="level-row"><span class="level-key">${label}</span><span class="level-val">${esc(String(lim[k]??'—'))}</span></div>`
      ).join('')}
    </div>
  `).join('');
}

async function loadAll(){
  document.getElementById('last-sync').textContent='syncing…';
  try{
    const [statsR,procsR,violsR,emergR,levelsR] = await Promise.all([
      get('/isolation/status'),
      get('/isolation/processes?limit=50'),
      get('/isolation/violations?limit=100'),
      get('/isolation/emergency?limit=50'),
      get('/isolation/levels'),
    ]);
    renderStats(statsR.stats||{});
    renderProcesses(procsR.processes||[]);
    renderViolations(violsR.violations||[]);
    renderEmergency(emergR.events||[]);
    renderLevels(levelsR.levels||{});
    document.getElementById('last-sync').textContent='synced '+new Date().toLocaleTimeString();
  }catch(e){
    console.error('loadAll',e);
    document.getElementById('last-sync').textContent='error: '+e.message;
  }
}
loadAll();
setInterval(loadAll,5000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.isolation_dashboard:app", host="0.0.0.0", port=8093, reload=True)
