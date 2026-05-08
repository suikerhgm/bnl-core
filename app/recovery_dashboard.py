"""
Nexus BNL — Recovery Dashboard
================================
Standalone FastAPI app for the Safe Restore System.

Features:
  - System integrity status
  - Snapshot list with checkpoint levels
  - Last SAFE checkpoint indicator
  - Restore event history
  - Rollback event history
  - Immutable audit trail
  - EMERGENCY RESTORE button (big red, requires confirmation)

Run:
    uvicorn app.recovery_dashboard:app --reload --port 8094
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.recovery_routes import router as recovery_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus Recovery Dashboard", docs_url="/api/docs", redoc_url=None)
app.include_router(recovery_router)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-recovery"})


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Nexus — Recovery Dashboard</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0b0b0f;--surface:#111118;--border:#1e1e2a;--muted:#3a3a50;
    --text:#c9d1d9;--dim:#666;
    --blue:#58a6ff;--green:#3fb950;--yellow:#e3b341;
    --red:#f85149;--purple:#bc8cff;--cyan:#39c5cf;--orange:#d4a72c;
    --mono:'Cascadia Code','Fira Code',Consolas,monospace;
  }
  body{font-family:var(--mono);background:var(--bg);color:var(--text);font-size:13px;min-height:100vh}

  #topbar{
    position:sticky;top:0;z-index:100;background:var(--surface);
    border-bottom:1px solid var(--border);padding:10px 20px;
    display:flex;align-items:center;gap:12px;
  }
  .logo{color:var(--green);font-size:15px;font-weight:700;letter-spacing:.04em}
  .logo-sub{color:var(--dim);font-size:11px}
  .chain-badge{padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;display:none}
  .chain-ok  {background:#0d2a15;color:var(--green);border:1px solid #1a5a30}
  .chain-fail{background:#2a0d0d;color:var(--red);border:1px solid #5a1515;animation:pulse 1s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
  #sync-btn{
    margin-left:auto;padding:4px 14px;font-size:11px;font-family:var(--mono);
    border-radius:4px;border:1px solid var(--muted);background:var(--surface);
    color:#aaa;cursor:pointer;
  }
  #sync-btn:hover{border-color:var(--green);color:var(--green)}
  #last-sync{color:var(--muted);font-size:10px;margin-left:8px}

  #content{padding:20px;max-width:1400px;margin:0 auto}

  /* EMERGENCY BUTTON */
  #emergency-section{
    background:linear-gradient(135deg,#1a0505 0%,#0f0f0f 100%);
    border:2px solid #5a1515;border-radius:8px;
    padding:20px;margin-bottom:22px;
    display:flex;align-items:center;gap:20px;flex-wrap:wrap;
  }
  .emergency-info{flex:1}
  .emergency-title{color:var(--red);font-size:13px;font-weight:700;letter-spacing:.05em}
  .emergency-desc{color:var(--dim);font-size:11px;margin-top:4px;line-height:1.5}
  .safe-snap-info{margin-top:8px;font-size:11px}
  .safe-snap-id{color:var(--green)}
  #emergency-btn{
    padding:12px 28px;font-size:13px;font-weight:700;font-family:var(--mono);
    border-radius:6px;border:2px solid var(--red);
    background:#2a0505;color:var(--red);cursor:pointer;
    letter-spacing:.05em;transition:all .15s;
    white-space:nowrap;
  }
  #emergency-btn:hover{background:#3a0808;border-color:#ff3030;color:#ff3030;box-shadow:0 0 16px rgba(248,81,73,.3)}
  #emergency-btn:disabled{opacity:.4;cursor:not-allowed}
  #emergency-btn.running{background:#1a0d00;border-color:var(--orange);color:var(--orange)}

  /* Stats */
  #stats-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:22px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:12px 14px}
  .stat-label{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
  .stat-value{font-size:24px;font-weight:700;margin-top:4px}
  .c-blue{color:var(--blue)}.c-green{color:var(--green)}.c-yellow{color:var(--yellow)}
  .c-red{color:var(--red)}.c-purple{color:var(--purple)}.c-cyan{color:var(--cyan)}

  /* Integrity panel */
  #integrity-panel{
    background:var(--surface);border:1px solid var(--border);
    border-radius:6px;padding:14px;margin-bottom:18px;
  }
  .int-title{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:10px}
  .int-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
  .int-item{background:#0e0e16;border-radius:4px;padding:10px;font-size:11px}
  .int-item-name{color:var(--dim);font-size:10px}
  .int-item-val{margin-top:3px;font-weight:700}
  .ok{color:var(--green)}.fail{color:var(--red)}.warn{color:var(--yellow)}

  /* Sections */
  .section{background:var(--surface);border:1px solid var(--border);border-radius:6px;margin-bottom:18px;overflow:hidden}
  .section-hdr{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
  .section-hdr .badge{margin-left:auto;background:#1a1a28;border-radius:10px;padding:1px 8px;font-size:11px;color:var(--muted)}
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:900px){.two-col{grid-template-columns:1fr}}

  /* Snapshot cards */
  #snap-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;padding:14px}
  .snap-card{background:#0e0e16;border:1px solid var(--border);border-radius:5px;padding:12px;cursor:pointer;transition:border-color .15s}
  .snap-card:hover{border-color:var(--blue)}
  .snap-card.SAFE    {border-left:3px solid var(--green)}
  .snap-card.STABLE  {border-left:3px solid var(--cyan)}
  .snap-card.TRUSTED {border-left:3px solid var(--purple)}
  .snap-card.NONE    {border-left:3px solid var(--muted)}
  .snap-id{font-size:10px;color:var(--dim)}
  .snap-label{font-size:12px;color:var(--text);margin-top:3px;font-weight:600}
  .snap-level{font-size:11px;margin-top:4px}
  .snap-row{display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap}

  /* Pills */
  .pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px}
  .pill-VALID  {background:#0d2a15;color:var(--green)}
  .pill-SAFE   {background:#0d2a20;color:var(--cyan)}
  .pill-STABLE {background:#0a2030;color:var(--cyan)}
  .pill-TRUSTED{background:#1a0d2a;color:var(--purple)}
  .pill-PENDING{background:#1a1a28;color:var(--muted)}
  .pill-INVALID{background:#2a0d0d;color:var(--red)}
  .pill-DELETED{background:#1a1a1a;color:#333}

  /* Tables */
  .data-table{width:100%;border-collapse:collapse}
  .data-table th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:6px 10px;border-bottom:1px solid var(--border)}
  .data-table td{padding:7px 10px;border-bottom:1px solid #161620;font-size:11px;vertical-align:top;word-break:break-all}
  .data-table tr:last-child td{border-bottom:none}
  .data-table tr:hover td{background:#0e0e18}

  /* Modal */
  #modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:999;display:none;align-items:center;justify-content:center}
  #modal-overlay.open{display:flex}
  #modal{background:#111118;border:1px solid #5a1515;border-radius:8px;padding:28px;max-width:420px;width:90%}
  #modal-title{color:var(--red);font-size:14px;font-weight:700;margin-bottom:12px}
  #modal-body{color:var(--dim);font-size:12px;line-height:1.6;margin-bottom:20px}
  #modal-progress{display:none;margin-bottom:16px}
  .progress-step{padding:4px 0;font-size:11px;color:var(--dim)}
  .progress-step.done{color:var(--green)}
  .progress-step.running{color:var(--yellow)}
  .modal-btns{display:flex;gap:10px;justify-content:flex-end}
  .btn-cancel{padding:6px 16px;font-size:11px;font-family:var(--mono);border-radius:4px;border:1px solid var(--muted);background:var(--surface);color:#aaa;cursor:pointer}
  .btn-confirm{padding:6px 16px;font-size:11px;font-family:var(--mono);border-radius:4px;border:1px solid var(--red);background:#2a0505;color:var(--red);cursor:pointer;font-weight:700}
  .btn-confirm:hover{background:#3a0808}

  .empty{padding:20px;text-align:center;color:var(--muted);font-size:11px}
  ::-webkit-scrollbar{width:5px}
  ::-webkit-scrollbar-track{background:var(--bg)}
  ::-webkit-scrollbar-thumb{background:var(--muted);border-radius:2px}
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">⟳ Nexus</span>
  <span style="color:var(--muted)">|</span>
  <span class="logo-sub">Recovery System</span>
  <span class="chain-badge" id="chain-badge">⛓ Chain Intact</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- EMERGENCY RESTORE -->
  <div id="emergency-section">
    <div class="emergency-info">
      <div class="emergency-title">⚠ EMERGENCY RESTORE</div>
      <div class="emergency-desc">
        Freeze runtime → kill dangerous processes → restore last SAFE checkpoint →
        validate integrity → resume services → generate forensic report.
      </div>
      <div class="safe-snap-info">
        Last SAFE snapshot: <span class="safe-snap-id" id="safe-snap-label">loading…</span>
      </div>
    </div>
    <button id="emergency-btn" onclick="openEmergencyModal()">
      ⚡ EMERGENCY RESTORE
    </button>
  </div>

  <!-- Stats -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Total Snapshots</div><div class="stat-value c-blue"   id="s-total">—</div></div>
    <div class="stat-card"><div class="stat-label">Safe</div><div class="stat-value c-green"  id="s-safe">—</div></div>
    <div class="stat-card"><div class="stat-label">Audit Entries</div><div class="stat-value c-purple" id="s-audit">—</div></div>
    <div class="stat-card"><div class="stat-label">Restores</div><div class="stat-value c-cyan"   id="s-rest">—</div></div>
    <div class="stat-card"><div class="stat-label">Rollbacks</div><div class="stat-value c-orange" id="s-roll">—</div></div>
    <div class="stat-card"><div class="stat-label">Chain</div><div class="stat-value c-green"  id="s-chain">—</div></div>
    <div class="stat-card"><div class="stat-label">Guardian</div><div class="stat-value c-green"  id="s-guard">—</div></div>
    <div class="stat-card"><div class="stat-label">Forensics</div><div class="stat-value c-yellow" id="s-forens">—</div></div>
  </div>

  <!-- Integrity panel -->
  <div id="integrity-panel">
    <div class="int-title">▪ Live System Integrity</div>
    <div class="int-grid" id="int-grid"><div class="empty">Loading…</div></div>
  </div>

  <!-- Snapshots -->
  <div class="section">
    <div class="section-hdr">▪ Snapshots <span class="badge" id="snap-badge">0</span></div>
    <div id="snap-grid"><div class="empty">Loading…</div></div>
  </div>

  <div class="two-col">

    <!-- Restore events -->
    <div class="section">
      <div class="section-hdr">▪ Restore History <span class="badge" id="rest-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Type</th><th>Files</th><th>OK</th></tr></thead>
          <tbody id="rest-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Audit trail -->
    <div class="section">
      <div class="section-hdr">▪ Audit Trail <span class="badge" id="audit-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Event</th><th>Description</th></tr></thead>
          <tbody id="audit-body"><tr><td colspan="3" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

  </div>

</div><!-- /content -->

<!-- Emergency modal -->
<div id="modal-overlay">
  <div id="modal">
    <div id="modal-title">⚡ Confirm Emergency Restore</div>
    <div id="modal-body">
      This will:<br>
      1. Freeze all running processes<br>
      2. Kill dangerous processes<br>
      3. Restore last SAFE checkpoint<br>
      4. Validate system integrity<br>
      5. Generate forensic report<br><br>
      <strong style="color:var(--red)">This action cannot be undone.</strong>
      Ensure you have a safe checkpoint before proceeding.
    </div>
    <div id="modal-progress">
      <div class="progress-step" id="step-freeze">⬜ Freezing runtime…</div>
      <div class="progress-step" id="step-forensic">⬜ Creating forensic snapshot…</div>
      <div class="progress-step" id="step-kill">⬜ Killing dangerous processes…</div>
      <div class="progress-step" id="step-restore">⬜ Restoring SAFE checkpoint…</div>
      <div class="progress-step" id="step-validate">⬜ Validating integrity…</div>
      <div class="progress-step" id="step-report">⬜ Generating forensic report…</div>
    </div>
    <div class="modal-btns">
      <button class="btn-cancel" id="modal-cancel" onclick="closeModal()">Cancel</button>
      <button class="btn-confirm" id="modal-confirm" onclick="executeEmergencyRestore()">⚡ EXECUTE</button>
    </div>
  </div>
</div>

<script>
async function get(url){const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json()}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function ts(s){return s?s.replace('T',' ').replace('Z',''):'—'}
function snapPill(s){return `<span class="pill pill-${s||'PENDING'}">${esc(s||'PENDING')}</span>`}

function levelColor(l){
  return l==='TRUSTED'?'var(--purple)':l==='STABLE'?'var(--cyan)':l==='SAFE'?'var(--green)':'var(--muted)'
}

function renderStats(s){
  document.getElementById('s-total').textContent  = s.total_snapshots ??'—';
  document.getElementById('s-safe').textContent   = s.safe_snapshots  ??'—';
  document.getElementById('s-audit').textContent  = s.audit_entries   ??'—';
  document.getElementById('s-rest').textContent   = s.restore_events  ??'—';
  document.getElementById('s-roll').textContent   = s.rollback_events ??'—';
  const chain = s.chain_intact;
  document.getElementById('s-chain').textContent  = chain?'OK':'FAIL';
  document.getElementById('s-chain').style.color  = chain?'var(--green)':'var(--red)';
  const badge = document.getElementById('chain-badge');
  badge.textContent = chain?'⛓ Chain Intact':'⚠ Chain Broken';
  badge.className = 'chain-badge ' + (chain?'chain-ok':'chain-fail');
  badge.style.display = 'inline-block';
  document.getElementById('s-forens').textContent = s.forensic_events ??'—';
}

function renderGuardian(g){
  const el = document.getElementById('s-guard');
  el.textContent = g.running?'ON':'OFF';
  el.style.color = g.running?'var(--green)':'var(--red)';
}

function renderIntegrity(int_data){
  const grid = document.getElementById('int-grid');
  const dbs = int_data.databases?.databases || {};
  const files = int_data.critical_files || {};
  const chain = int_data.chain?.intact;

  let html = '';
  html += `<div class="int-item">
    <div class="int-item-name">Audit Chain</div>
    <div class="int-item-val ${chain?'ok':'fail'}">${chain?'✓ Intact':'✗ Broken'}</div>
  </div>`;
  html += `<div class="int-item">
    <div class="int-item-name">Critical Files</div>
    <div class="int-item-val ${files.healthy?'ok':'fail'}">${files.healthy?'✓ All Present':'✗ Missing: '+files.missing?.length}</div>
  </div>`;
  for(const [name,r] of Object.entries(dbs)){
    html += `<div class="int-item">
      <div class="int-item-name">${esc(name)}</div>
      <div class="int-item-val ${r.ok?'ok':'fail'}">${r.ok?'✓ OK':'✗ '+esc(r.message)}</div>
    </div>`;
  }
  grid.innerHTML = html;
}

function renderLatestSafe(snap){
  const el = document.getElementById('safe-snap-label');
  if(snap){
    el.textContent = snap.snapshot_id.slice(0,16)+'… ('+ts(snap.created_at)+')';
    el.style.color = 'var(--green)';
  } else {
    el.textContent = 'No SAFE snapshot available';
    el.style.color = 'var(--red)';
    document.getElementById('emergency-btn').disabled = true;
  }
}

function renderSnapshots(snaps){
  const grid = document.getElementById('snap-grid');
  document.getElementById('snap-badge').textContent = snaps.length;
  if(!snaps.length){grid.innerHTML='<div class="empty">No snapshots yet</div>';return}
  grid.innerHTML = snaps.map(s=>`
    <div class="snap-card ${s.checkpoint_level||'NONE'}">
      <div class="snap-id">${esc(s.snapshot_id)}</div>
      <div class="snap-label">${esc(s.label||'(unlabeled)')}</div>
      <div class="snap-row">
        ${snapPill(s.status)}
        <span style="color:${levelColor(s.checkpoint_level)};font-size:10px;font-weight:700">${esc(s.checkpoint_level||'NONE')}</span>
      </div>
      <div style="font-size:10px;color:var(--dim);margin-top:6px">${ts(s.created_at)}</div>
      <div style="font-size:10px;color:var(--muted)">${s.files_count} files · ${(s.size_bytes/1024).toFixed(0)}KB</div>
    </div>
  `).join('');
}

function renderRestoreEvents(events){
  const tbody = document.getElementById('rest-body');
  document.getElementById('rest-badge').textContent = events.length;
  if(!events.length){tbody.innerHTML='<tr><td colspan="4" class="empty">No restores yet</td></tr>';return}
  tbody.innerHTML = events.slice(0,30).map(e=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(e.started_at)}</td>
    <td style="color:var(--cyan)">${esc(e.restore_type)}</td>
    <td style="color:var(--text)">${e.files_restored||0}</td>
    <td style="color:${e.success?'var(--green)':'var(--red)'}">${e.success?'✓':'✗'}</td>
  </tr>`).join('');
}

function renderAudit(entries){
  const tbody = document.getElementById('audit-body');
  document.getElementById('audit-badge').textContent = entries.length;
  if(!entries.length){tbody.innerHTML='<tr><td colspan="3" class="empty">No audit entries</td></tr>';return}
  tbody.innerHTML = entries.slice(0,40).map(e=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(e.timestamp)}</td>
    <td style="color:var(--blue)">${esc(e.event_type)}</td>
    <td style="color:var(--dim)">${esc(e.description.slice(0,60))}</td>
  </tr>`).join('');
}

// ── Emergency modal ────────────────────────────────────────────────────────────

function openEmergencyModal(){
  document.getElementById('modal-progress').style.display='none';
  document.getElementById('modal-confirm').disabled=false;
  document.getElementById('modal-cancel').disabled=false;
  document.getElementById('modal-confirm').textContent='⚡ EXECUTE';
  ['step-freeze','step-forensic','step-kill','step-restore','step-validate','step-report'].forEach(id=>{
    const el=document.getElementById(id);
    el.className='progress-step';
    el.textContent=el.textContent.replace(/[✓✗⟳]/,'⬜');
  });
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal(){
  if(!document.getElementById('modal-confirm').disabled)
    document.getElementById('modal-overlay').classList.remove('open');
}

function setStep(id, state){
  const el=document.getElementById(id);
  const icons={'running':'⟳','done':'✓','fail':'✗'};
  el.className='progress-step '+state;
  el.textContent=el.textContent.replace(/[⬜✓✗⟳ ]/,'').trim();
  el.textContent=icons[state]+' '+el.textContent;
}

async function executeEmergencyRestore(){
  document.getElementById('modal-confirm').disabled=true;
  document.getElementById('modal-cancel').disabled=true;
  document.getElementById('modal-confirm').textContent='Running…';
  const prog=document.getElementById('modal-progress');
  prog.style.display='block';

  const steps=['step-freeze','step-forensic','step-kill','step-restore','step-validate','step-report'];
  steps.forEach(s=>setStep(s,'running'));

  try{
    const res = await post('/recovery/emergency_restore',{triggered_by:'emergency_button',confirm:true});
    steps.forEach(s=>setStep(s, res.success?'done':'fail'));
    document.getElementById('modal-confirm').textContent = res.success?'✓ Done':'✗ Failed';
    setTimeout(()=>{
      closeModal();
      loadAll();
    }, 2000);
  }catch(e){
    steps.forEach(s=>setStep(s,'fail'));
    document.getElementById('modal-confirm').textContent='✗ Error';
    setTimeout(()=>document.getElementById('modal-cancel').disabled=false, 1000);
  }
}

// ── Load all ───────────────────────────────────────────────────────────────────
async function loadAll(){
  document.getElementById('last-sync').textContent='syncing…';
  try{
    const [statusR,snapsR,restR,auditR,intR,guardR] = await Promise.all([
      get('/recovery/status'),
      get('/recovery/snapshots?limit=50'),
      get('/recovery/restore_events?limit=30'),
      get('/recovery/audit?limit=50'),
      get('/recovery/integrity'),
      get('/recovery/guardian'),
    ]);
    const stats = {...(statusR.stats||{}), ...(statusR.stats||{})};
    renderStats(statusR.stats||{});
    renderGuardian(guardR);
    renderIntegrity(intR);
    renderSnapshots(snapsR.snapshots||[]);
    renderRestoreEvents(restR.events||[]);
    renderAudit(auditR.entries||[]);

    // Latest safe
    const safe = (snapsR.snapshots||[]).find(s=>['SAFE','STABLE','TRUSTED'].includes(s.checkpoint_level));
    renderLatestSafe(safe||null);

    document.getElementById('last-sync').textContent='synced '+new Date().toLocaleTimeString();
  }catch(e){
    console.error('loadAll',e);
    document.getElementById('last-sync').textContent='error: '+e.message;
  }
}

loadAll();
setInterval(loadAll,10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.recovery_dashboard:app", host="0.0.0.0", port=8094, reload=True)
