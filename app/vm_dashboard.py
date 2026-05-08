# app/vm_dashboard.py
"""
VM Isolation Dashboard — single-file Flask dashboard.
Panels: Capability Map, Active VMs, Negotiation Feed,
        Escape Attempts, Audit Trail (hash-chain indicator),
        Risk Heatmap, Isolation Confidence Score.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template_string

app = Flask(__name__)

_DB = Path("data/nexus_vm_isolation.db")

_TIER_META = {
    "FIRECRACKER":    {"num": 1, "score": 95},
    "QEMU":           {"num": 2, "score": 82},
    "DOCKER_HARDENED":{"num": 3, "score": 70},
    "SANDBOX":        {"num": 4, "score": 40},
    "PROCESS_JAIL":   {"num": 5, "score": 20},
}

_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Nexus — VM Isolation</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Courier New',monospace;background:#0d1117;color:#e6edf3;padding:20px;}
  h1{color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:8px;margin-bottom:16px;}
  h2{color:#79c0ff;font-size:.8em;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px;}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;}
  .card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:14px;}
  .badge{display:inline-block;padding:1px 7px;border-radius:4px;font-size:.72em;font-weight:700;margin-right:4px;}
  .t1{background:#2ea043;}.t2{background:#1f6feb;}.t3{background:#9e6a03;}
  .t4{background:#1c4b8c;}.t5{background:#333;}
  .ok{color:#3fb950;}.warn{color:#d29922;}.crit{color:#f85149;}.dim{color:#484f58;}
  table{width:100%;border-collapse:collapse;font-size:.8em;margin-top:6px;}
  th{color:#8b949e;padding:3px 6px;border-bottom:1px solid #21262d;text-align:left;}
  td{padding:3px 6px;border-bottom:1px solid #0d1117;}
  .bar{height:5px;background:#21262d;border-radius:3px;margin-top:3px;}
  .fill{height:100%;border-radius:3px;}
  .green{background:#3fb950;}.yellow{background:#d29922;}.red{background:#f85149;}
  .ts{font-size:.72em;color:#484f58;}
  .chain-ok{color:#3fb950;font-weight:700;}.chain-bad{color:#f85149;font-weight:700;}
</style>
</head>
<body>
<h1>&#x1F6E1; Nexus VM Isolation Dashboard</h1>
<p class="ts">{{ now }} — auto-refresh 5s</p>
<div class="grid" style="margin-top:12px;">

  <!-- Capability Map -->
  <div class="card">
    <h2>&#x1F50D; Capability Map</h2>
    {% for name,num,avail,score in tiers %}
    <div style="margin:5px 0;display:flex;align-items:center;gap:6px;">
      <span class="badge t{{ num }}">T{{ num }}</span>
      <span>{{ name }}</span>
      {% if avail %}<span class="ok" style="margin-left:auto;">&#x2713; available</span>
      {% else %}<span class="dim" style="margin-left:auto;">&#x2715; unavailable</span>{% endif %}
      {% if avail %}<span style="color:#58a6ff;font-size:.8em;">{{ score }}</span>{% endif %}
    </div>
    {% endfor %}
    <div class="ts" style="margin-top:8px;">
      OS: {{ cap.host_os }} | Docker: {{ cap.docker_runtime or 'none' }} | Virt: {{ cap.virtualization_type or 'none' }}
    </div>
  </div>

  <!-- Isolation Confidence -->
  <div class="card">
    <h2>&#x1F4CA; Isolation Confidence</h2>
    {% for vm in vms[:5] %}
    <div style="margin:5px 0;">
      <div style="display:flex;justify-content:space-between;">
        <span class="ts">{{ vm.vm_id[:8] }}…</span>
        <span class="badge t{{ vm.tier_num }}">{{ vm.tier }}</span>
        <span>{{ vm.confidence }}</span>
      </div>
      <div class="bar"><div class="fill {{ vm.conf_color }}" style="width:{{ vm.confidence }}%"></div></div>
    </div>
    {% else %}
    <p class="ts" style="margin-top:6px;">No active VMs</p>
    {% endfor %}
  </div>

  <!-- Active VMs -->
  <div class="card">
    <h2>&#x1F5A5; Active VMs</h2>
    {% if vms %}
    <table>
      <tr><th>ID</th><th>Tier</th><th>Status</th><th>Score</th></tr>
      {% for vm in vms %}
      <tr>
        <td class="ts">{{ vm.vm_id[:8] }}…</td>
        <td><span class="badge t{{ vm.tier_num }}">{{ vm.tier }}</span></td>
        <td class="{{ 'ok' if vm.status=='RUNNING' else 'warn' }}">{{ vm.status }}</td>
        <td>{{ vm.security_score or '-' }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<p class="ts" style="margin-top:6px;">No VMs</p>{% endif %}
  </div>

  <!-- Negotiation Feed -->
  <div class="card">
    <h2>&#x1F4AC; Negotiation Feed</h2>
    {% if negotiations %}
    <table>
      <tr><th>Requested</th><th>Actual</th><th>Policy</th><th>Level</th></tr>
      {% for n in negotiations %}
      <tr>
        <td>{{ n.requested or 'best' }}</td>
        <td><span class="badge t{{ n.tier_num }}">{{ n.actual }}</span></td>
        <td class="ts">{{ n.policy }}</td>
        <td class="{{ 'warn' if n.fallback > 0 else 'ok' }}">{{ n.fallback }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<p class="ts" style="margin-top:6px;">No negotiations yet</p>{% endif %}
  </div>

  <!-- Escape Attempts -->
  <div class="card">
    <h2>&#x26A0; Escape Attempts</h2>
    {% if threats %}
    <table>
      <tr><th>Signal</th><th>VM</th><th>Severity</th></tr>
      {% for t in threats %}
      <tr>
        <td>{{ t.signal_type }}</td>
        <td class="ts">{{ t.vm_id[:8] if t.vm_id else '-' }}…</td>
        <td class="{{ 'crit' if t.severity=='CRITICAL' else 'warn' }}">{{ t.severity }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<p class="ok ts" style="margin-top:6px;">No escape attempts</p>{% endif %}
  </div>

  <!-- Audit Trail -->
  <div class="card">
    <h2>&#x1F4DC; Audit Trail</h2>
    <div>Chain: <span class="{{ 'chain-ok' if chain_ok else 'chain-bad' }}">
      {{ '&#x2713; intact' if chain_ok else '&#x2717; BROKEN' }}</span></div>
    {% if events %}
    <table style="margin-top:6px;">
      <tr><th>Type</th><th>Severity</th><th>Time</th></tr>
      {% for e in events %}
      <tr>
        <td>{{ e.event_type }}</td>
        <td class="{{ 'ok' if e.severity=='INFO' else ('warn' if e.severity=='WARNING' else 'crit') }}">
          {{ e.severity }}</td>
        <td class="ts">{{ e.timestamp[:19] if e.timestamp else '-' }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}<p class="ts" style="margin-top:6px;">No events yet</p>{% endif %}
  </div>

</div>
</body>
</html>
"""


def _read_db() -> dict:
    if not _DB.exists():
        return {}
    try:
        with sqlite3.connect(str(_DB)) as conn:
            conn.row_factory = sqlite3.Row
            vms = [dict(r) for r in conn.execute(
                "SELECT vm_id, tier, status, security_score, risk_adjusted_score, "
                "fallback_level, agent_id FROM virtual_machines "
                "WHERE status NOT IN ('DESTROYED') ORDER BY created_at DESC LIMIT 20"
            )]
            negs = [dict(r) for r in conn.execute(
                "SELECT session_id, requested_tier, actual_tier, policy, "
                "negotiation_result, started_at FROM vm_sessions "
                "ORDER BY started_at DESC LIMIT 10"
            )]
            threats = [dict(r) for r in conn.execute(
                "SELECT vm_id, signal_type, severity FROM vm_escape_attempts "
                "ORDER BY timestamp DESC LIMIT 10"
            )]
            events = [dict(r) for r in conn.execute(
                "SELECT event_type, severity, vm_id, timestamp FROM vm_events "
                "ORDER BY timestamp DESC LIMIT 15"
            )]
        return {"vms": vms, "negotiations": negs, "threats": threats, "events": events}
    except Exception:
        return {}


def _confidence(vm: dict) -> tuple[int, str]:
    base = vm.get("security_score") or _TIER_META.get(vm.get("tier", ""), {}).get("score", 20)
    fb_penalty = (vm.get("fallback_level") or 0) * 10
    score = max(0, min(100, base - fb_penalty))
    color = "green" if score >= 70 else ("yellow" if score >= 40 else "red")
    return score, color


@app.route("/")
@app.route("/vm/dashboard")
def dashboard():
    from core.isolation_abstraction.isolation_capability_detector import get_capability_detector
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger

    cap = get_capability_detector().detect()
    data = _read_db()

    available_names = {t.name for t in cap.available_tiers}
    tiers = [
        ("FIRECRACKER",     1, "FIRECRACKER" in available_names,     95),
        ("QEMU",            2, "QEMU" in available_names,            82),
        ("DOCKER_HARDENED", 3, "DOCKER_HARDENED" in available_names, 70),
        ("SANDBOX",         4, True,                                  40),
        ("PROCESS_JAIL",    5, True,                                  20),
    ]

    vms = []
    for vm in data.get("vms", []):
        meta = _TIER_META.get(vm.get("tier", ""), {"num": 5, "score": 20})
        conf, color = _confidence(vm)
        vms.append({**vm, "tier_num": meta["num"], "confidence": conf, "conf_color": color})

    negotiations = []
    for n in data.get("negotiations", []):
        actual = n.get("actual_tier", "?")
        meta = _TIER_META.get(actual, {"num": 5})
        try:
            nr = json.loads(n.get("negotiation_result") or "{}")
            fallback = nr.get("fallback_level", 0)
        except Exception:
            fallback = 0
        negotiations.append({
            "requested": n.get("requested_tier"),
            "actual": actual,
            "tier_num": meta["num"],
            "policy": n.get("policy", ""),
            "fallback": fallback,
        })

    chain_ok = True
    try:
        logger = IsolationAuditLogger()
        chain_ok = logger.verify_chain()
    except Exception:
        pass

    return render_template_string(
        _TEMPLATE,
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        cap=cap,
        tiers=tiers,
        vms=vms,
        negotiations=negotiations,
        threats=data.get("threats", []),
        events=data.get("events", []),
        chain_ok=chain_ok,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False)
