"""
Nexus BNL — Sandbox Dashboard
================================
Standalone FastAPI app for the Sandbox System.

Shows:
  - System-wide sandbox stats
  - Active / quarantined / completed sandboxes
  - Risk scores and violation counts
  - Resource usage (CPU / RAM charts)
  - Event log per sandbox
  - Violation breakdown
  - Mode configuration reference

Run:
    uvicorn app.sandbox_dashboard:app --reload --port 8092
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.sandbox_routes import router as sandbox_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus Sandbox Dashboard", docs_url="/api/docs", redoc_url=None)
app.include_router(sandbox_router)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-sandbox"})


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus — Sandbox Dashboard</title>
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
  .logo { color:var(--orange); font-size:15px; font-weight:700; letter-spacing:.04em; }
  .logo-sep { color:var(--muted); }
  .logo-sub { color:var(--dim); font-size:11px; }
  #sync-btn {
    margin-left:auto; padding:4px 14px; font-size:11px; font-family:var(--mono);
    border-radius:4px; border:1px solid var(--muted);
    background:var(--surface); color:#aaa; cursor:pointer;
  }
  #sync-btn:hover { border-color:var(--orange); color:var(--orange); }
  #last-sync { color:var(--muted); font-size:10px; margin-left:8px; }

  /* ── Layout ── */
  #content { padding:20px; max-width:1400px; margin:0 auto; }

  /* ── Stat cards ── */
  #stats-row { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:22px; }
  .stat-card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:12px 14px; }
  .stat-label { font-size:10px; color:var(--dim); text-transform:uppercase; letter-spacing:.06em; }
  .stat-value { font-size:24px; font-weight:700; margin-top:4px; }
  .c-blue{color:var(--blue)} .c-green{color:var(--green)} .c-yellow{color:var(--yellow)}
  .c-red{color:var(--red)}   .c-purple{color:var(--purple)} .c-cyan{color:var(--cyan)} .c-orange{color:var(--orange)}

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

  /* ── Sandbox cards grid ── */
  #sb-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
  .sb-card {
    background:#0e0e16; border:1px solid var(--border); border-radius:5px; padding:14px;
    cursor:pointer; transition:border-color .15s;
  }
  .sb-card:hover { border-color:var(--blue); }
  .sb-card.quarantined { border-left:3px solid var(--red); background:#1a0a0a; }
  .sb-card.running     { border-left:3px solid var(--green); }
  .sb-card.frozen      { border-left:3px solid var(--cyan); }
  .sb-card.completed   { border-left:3px solid var(--muted); }

  .sb-id    { font-size:10px; color:var(--dim); font-family:var(--mono); }
  .sb-mode  { font-size:11px; color:var(--cyan); margin-top:3px; }
  .sb-agent { font-size:11px; color:var(--purple); }
  .sb-row   { display:flex; align-items:center; gap:8px; margin-top:6px; }
  .sb-risk  { font-size:11px; }

  /* ── Risk bar ── */
  .risk-bar { display:inline-block; width:80px; height:5px; border-radius:3px; background:var(--border); position:relative; vertical-align:middle; }
  .risk-fill { position:absolute; left:0; top:0; bottom:0; border-radius:3px; }

  /* ── Pills ── */
  .pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:10px; }
  .pill-running     { background:#0d2a15; color:var(--green); }
  .pill-frozen      { background:#0d2228; color:var(--cyan); }
  .pill-quarantined { background:#2a0d0d; color:var(--red); border:1px solid #5a1515; }
  .pill-completed   { background:#1a1a28; color:var(--muted); }
  .pill-created     { background:#1a1a28; color:var(--blue); }
  .pill-destroyed   { background:#1a1a1a; color:#333; }
  .pill-critical    { background:#2a0d0d; color:var(--red); }
  .pill-warning     { background:#2a200d; color:var(--yellow); }
  .pill-info        { background:#0d1a28; color:var(--blue); }

  /* ── Tables ── */
  .data-table { width:100%; border-collapse:collapse; }
  .data-table th { text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); padding:6px 10px; border-bottom:1px solid var(--border); }
  .data-table td { padding:7px 10px; border-bottom:1px solid #161620; font-size:11px; vertical-align:top; word-break:break-word; }
  .data-table tr:last-child td { border-bottom:none; }
  .data-table tr:hover td { background:#0e0e18; }

  /* ── Mode reference ── */
  #modes-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }
  .mode-card { background:#0e0e16; border:1px solid var(--border); border-radius:5px; padding:12px; }
  .mode-name { font-size:11px; font-weight:700; color:var(--orange); margin-bottom:8px; }
  .mode-row  { display:flex; justify-content:space-between; font-size:10px; padding:2px 0; }
  .mode-key  { color:var(--dim); }
  .mode-val  { color:var(--text); }

  /* ── Detail panel ── */
  #detail-panel {
    position:fixed; right:0; top:0; bottom:0; width:420px;
    background:#0f0f1a; border-left:1px solid var(--border);
    display:none; flex-direction:column; z-index:200; overflow:hidden;
  }
  #detail-panel.open { display:flex; }
  #detail-hdr {
    padding:12px 14px; border-bottom:1px solid var(--border);
    display:flex; align-items:center; gap:8px; flex-shrink:0;
  }
  #detail-hdr .title { flex:1; font-size:12px; color:var(--text); }
  #close-detail { background:none; border:none; color:var(--dim); cursor:pointer; font-size:16px; }
  #close-detail:hover { color:var(--text); }
  #detail-body { flex:1; overflow-y:auto; padding:14px; }

  .det-section { margin-bottom:14px; }
  .det-label { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:6px; }
  .det-row { display:flex; justify-content:space-between; font-size:11px; padding:3px 0; border-bottom:1px solid #1a1a28; }
  .det-key { color:var(--dim); }
  .det-val { color:var(--text); max-width:60%; text-align:right; word-break:break-all; }

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
  <span class="logo">⬡ Nexus</span>
  <span class="logo-sep">|</span>
  <span class="logo-sub">Sandbox System</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- Stats -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value c-blue"   id="s-total">—</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value c-green"  id="s-active">—</div></div>
    <div class="stat-card"><div class="stat-label">Quarantined</div><div class="stat-value c-red"    id="s-quar">—</div></div>
    <div class="stat-card"><div class="stat-label">Completed</div><div class="stat-value c-muted"  id="s-comp">—</div></div>
    <div class="stat-card"><div class="stat-label">Destroyed</div><div class="stat-value c-dim"   id="s-dest">—</div></div>
    <div class="stat-card"><div class="stat-label">Violations</div><div class="stat-value c-orange" id="s-viol">—</div></div>
    <div class="stat-card"><div class="stat-label">Events</div><div class="stat-value c-purple" id="s-evts">—</div></div>
    <div class="stat-card"><div class="stat-label">Critical</div><div class="stat-value c-red"   id="s-crit">—</div></div>
  </div>

  <!-- Quarantined sandboxes -->
  <div class="section" id="quar-section" style="border-left:3px solid var(--red)">
    <div class="section-hdr">⚠ Quarantined Sandboxes <span class="badge" id="quar-badge">0</span></div>
    <div class="section-body">
      <div id="quar-grid"><div class="empty" style="color:var(--green)">✓ No quarantined sandboxes</div></div>
    </div>
  </div>

  <!-- All sandboxes -->
  <div class="section">
    <div class="section-hdr">▪ All Sandboxes <span class="badge" id="sb-badge">0</span></div>
    <div class="section-body">
      <div id="sb-grid"><div class="empty">Loading…</div></div>
    </div>
  </div>

  <div class="two-col">

    <!-- Recent events -->
    <div class="section">
      <div class="section-hdr">▪ Recent Events <span class="badge" id="events-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Sandbox</th><th>Type</th><th>Sev</th></tr></thead>
          <tbody id="events-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Mode reference -->
    <div class="section">
      <div class="section-hdr">▪ Sandbox Modes</div>
      <div class="section-body">
        <div id="modes-grid"><div class="empty">Loading…</div></div>
      </div>
    </div>

  </div>

</div><!-- /content -->

<!-- Detail panel -->
<div id="detail-panel">
  <div id="detail-hdr">
    <span class="title" id="detail-title">Sandbox Detail</span>
    <button id="close-detail" onclick="closeDetail()">✕</button>
  </div>
  <div id="detail-body">
    <div class="empty">Loading…</div>
  </div>
</div>

<script>
async function get(url){
  const r = await fetch(url);
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function ts(s){ return s?s.replace('T',' ').replace('Z',''):'—'; }
function sevPill(s){ const m={CRITICAL:'critical',WARNING:'warning',INFO:'info'}; return `<span class="pill pill-${m[s]||'info'}">${esc(s||'INFO')}</span>`; }
function statusPill(s){ return `<span class="pill pill-${s||'created'}">${esc(s||'created')}</span>`; }

function riskFill(score){
  const c = score>=80?'var(--red)':score>=50?'var(--orange)':score>=20?'var(--yellow)':'var(--green)';
  return `<span class="risk-bar"><span class="risk-fill" style="width:${score}%;background:${c}"></span></span>`;
}

function renderStats(s){
  document.getElementById('s-total').textContent  = s.total_sandboxes  ??'—';
  document.getElementById('s-active').textContent = s.active_sandboxes ??'—';
  document.getElementById('s-quar').textContent   = s.quarantined      ??'—';
  document.getElementById('s-comp').textContent   = s.completed        ??'—';
  document.getElementById('s-dest').textContent   = s.destroyed        ??'—';
  document.getElementById('s-viol').textContent   = s.open_violations  ??'—';
  document.getElementById('s-evts').textContent   = s.total_events     ??'—';
  document.getElementById('s-crit').textContent   = s.critical_events  ??'—';
}

function sbCard(sb, isQuar){
  const cls = `sb-card ${sb.status||'created'}`;
  const risk = sb.risk_score||0;
  return `<div class="${cls}" onclick="openDetail('${esc(sb.sandbox_id)}')">
    <div class="sb-id">${esc(sb.sandbox_id)}</div>
    <div class="sb-mode">${esc(sb.mode)}</div>
    ${sb.agent_id?`<div class="sb-agent">agent: ${esc(sb.agent_id)}</div>`:''}
    <div class="sb-row">
      ${statusPill(sb.status)}
      ${riskFill(risk)}
      <span class="sb-risk" style="color:${risk>=60?'var(--red)':risk>=30?'var(--yellow)':'var(--green)'}">${risk}</span>
    </div>
    <div style="font-size:10px;color:var(--dim);margin-top:6px">${ts(sb.created_at)}</div>
  </div>`;
}

function renderSandboxes(sbs){
  const grid = document.getElementById('sb-grid');
  const quarGrid = document.getElementById('quar-grid');
  document.getElementById('sb-badge').textContent = sbs.length;

  const quarantined = sbs.filter(s=>s.status==='quarantined');
  document.getElementById('quar-badge').textContent = quarantined.length;

  if(!sbs.length){ grid.innerHTML='<div class="empty">No sandboxes</div>'; }
  else grid.innerHTML = sbs.map(sb=>sbCard(sb,false)).join('');

  if(!quarantined.length) quarGrid.innerHTML='<div class="empty" style="color:var(--green)">✓ No quarantined sandboxes</div>';
  else quarGrid.innerHTML = quarantined.map(sb=>sbCard(sb,true)).join('');
}

function renderEvents(events){
  const tbody = document.getElementById('events-body');
  document.getElementById('events-badge').textContent = events.length;
  if(!events.length){ tbody.innerHTML='<tr><td colspan="4" class="empty">No events</td></tr>'; return; }
  tbody.innerHTML = events.slice(0,60).map(e=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(e.timestamp)}</td>
    <td style="color:var(--blue);font-size:10px">${esc((e.sandbox_id||'').slice(0,8))}</td>
    <td style="color:var(--text)">${esc(e.event_type)}</td>
    <td>${sevPill(e.severity)}</td>
  </tr>`).join('');
}

function renderModes(modes){
  const grid = document.getElementById('modes-grid');
  const labels = {
    allow_exec:'Exec',allow_network:'Net',allow_fs_write:'FS Write',
    max_cpu_pct:'Max CPU%',max_ram_mb:'Max RAM (MB)',max_duration_sec:'Timeout (s)',
    auto_quarantine_score:'Auto-Q Score',
  };
  grid.innerHTML = Object.entries(modes).map(([name,cfg])=>`
    <div class="mode-card">
      <div class="mode-name">${esc(name)}</div>
      ${Object.entries(labels).map(([k,label])=>`
        <div class="mode-row">
          <span class="mode-key">${label}</span>
          <span class="mode-val">${esc(String(cfg[k]??'—'))}</span>
        </div>
      `).join('')}
    </div>
  `).join('');
}

// ── Detail panel ───────────────────────────────────────────────────────────────
async function openDetail(sandboxId){
  const panel = document.getElementById('detail-panel');
  const body  = document.getElementById('detail-body');
  const title = document.getElementById('detail-title');
  title.textContent = sandboxId.slice(0,16)+'…';
  panel.classList.add('open');
  body.innerHTML = '<div class="empty">Loading…</div>';

  try {
    const [sbR, evtR, violR, snapR] = await Promise.all([
      get('/sandbox/'+sandboxId),
      get('/sandbox/'+sandboxId+'/events?limit=30'),
      get('/sandbox/'+sandboxId+'/violations'),
      get('/sandbox/'+sandboxId+'/snapshots?limit=5'),
    ]);
    const sb = sbR.sandbox||{};
    const events = evtR.events||[];
    const viols  = violR.violations||[];
    const snap   = (snapR.snapshots||[])[0];

    body.innerHTML = `
      <div class="det-section">
        <div class="det-label">Info</div>
        ${detRow('ID', sb.sandbox_id)}
        ${detRow('Mode', sb.mode)}
        ${detRow('Status', sb.status)}
        ${detRow('Agent', sb.agent_id||'—')}
        ${detRow('Risk', sb.risk_score)}
        ${detRow('Created', ts(sb.created_at))}
        ${detRow('Started', ts(sb.started_at))}
        ${sb.quarantined_at?detRow('Quarantined', ts(sb.quarantined_at)):''}
      </div>

      ${snap?`<div class="det-section">
        <div class="det-label">Last Snapshot</div>
        ${detRow('CPU %', snap.cpu_percent)}
        ${detRow('RAM MB', snap.ram_mb)}
        ${detRow('Open Files', snap.open_files)}
        ${detRow('Children', snap.child_processes)}
        ${detRow('Net Conns', snap.net_connections)}
      </div>`:''}

      <div class="det-section">
        <div class="det-label">Violations (${viols.length})</div>
        ${viols.length?viols.map(v=>`
          <div style="padding:5px 0;border-bottom:1px solid var(--border)">
            <div style="color:var(--red);font-size:11px">${esc(v.violation_type)}</div>
            <div style="color:var(--dim);font-size:10px">${esc(v.description.slice(0,80))}</div>
            <div style="color:var(--muted);font-size:10px">+${v.risk_delta} risk</div>
          </div>
        `).join(''):'<div style="color:var(--green);font-size:11px">✓ No violations</div>'}
      </div>

      <div class="det-section">
        <div class="det-label">Recent Events (${events.length})</div>
        ${events.map(e=>`
          <div style="padding:4px 0;border-bottom:1px solid var(--border)">
            <div style="display:flex;gap:6px;align-items:center">
              ${sevPill(e.severity)}
              <span style="color:var(--text);font-size:11px">${esc(e.event_type)}</span>
            </div>
            <div style="color:var(--dim);font-size:10px">${esc(e.description.slice(0,80))}</div>
          </div>
        `).join('')}
      </div>
    `;
  } catch(e){
    body.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
  }
}

function detRow(k,v){
  return `<div class="det-row"><span class="det-key">${esc(k)}</span><span class="det-val">${esc(String(v??'—'))}</span></div>`;
}

function closeDetail(){
  document.getElementById('detail-panel').classList.remove('open');
}

// ── Load all ───────────────────────────────────────────────────────────────────
async function loadAll(){
  document.getElementById('last-sync').textContent='syncing…';
  try {
    const [statsR, sbsR, evtsR, modesR] = await Promise.all([
      get('/sandbox/status'),
      get('/sandbox/list?limit=100'),
      get('/sandbox/list?limit=1'),  // just to get recent events from all
      get('/sandbox/modes'),
    ]);

    renderStats(statsR.stats||{});
    renderSandboxes(sbsR.sandboxes||[]);
    renderModes(modesR.modes||{});

    // Load recent events across all sandboxes by querying the audit logger directly
    // (approximated by fetching events for each sandbox in the list)
    const sbs = sbsR.sandboxes||[];
    let allEvents = [];
    for(const sb of sbs.slice(0,10)){
      try {
        const r = await get('/sandbox/'+sb.sandbox_id+'/events?limit=10');
        allEvents = allEvents.concat(r.events||[]);
      } catch(_){}
    }
    allEvents.sort((a,b)=>(b.timestamp||'').localeCompare(a.timestamp||''));
    renderEvents(allEvents.slice(0,60));

    document.getElementById('last-sync').textContent='synced '+new Date().toLocaleTimeString();
  } catch(e){
    console.error('loadAll',e);
    document.getElementById('last-sync').textContent='error: '+e.message;
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
    uvicorn.run("app.sandbox_dashboard:app", host="0.0.0.0", port=8092, reload=True)
