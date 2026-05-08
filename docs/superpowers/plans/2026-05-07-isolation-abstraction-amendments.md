# Plan A — Amendments (Approved 2026-05-07)

These amendments supersede or extend specific tasks in
`2026-05-07-isolation-abstraction-plan.md`. Implement these changes
when executing each task. The original plan structure (12 tasks) remains.

---

## Task 1 — Core Types (isolation_driver.py)

### RuntimeHandle: immutable internal state

Replace `_internal: dict` with a module-level registry pattern.
`RuntimeHandle` itself becomes truly immutable. Drivers call
`_set_handle_state` / `_get_handle_state` — callers never touch internals.

```python
# At module level in isolation_driver.py
_handle_state_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()

def _set_handle_state(runtime_id: str, key: str, value: object) -> None:
    with _registry_lock:
        _handle_state_registry.setdefault(runtime_id, {})[key] = value

def _get_handle_state(runtime_id: str, key: str, default=None) -> object:
    with _registry_lock:
        return _handle_state_registry.get(runtime_id, {}).get(key, default)

def _clear_handle_state(runtime_id: str) -> None:
    with _registry_lock:
        _handle_state_registry.pop(runtime_id, None)

@dataclass(frozen=True)
class RuntimeHandle:
    runtime_id: str
    runtime_type: str
    tier: IsolationTier
    created_at: datetime
    state: RuntimeLifecycleState = RuntimeLifecycleState.CREATED
    # NO _internal field. Use _set/get_handle_state(runtime_id, ...).
```

All driver code that previously wrote `handle._internal["x"] = y`
now calls `_set_handle_state(handle.runtime_id, "x", y)`.

### RuntimeLifecycleState

Add before `RuntimeHandle`:

```python
class RuntimeLifecycleState(str, Enum):
    CREATED      = "created"
    RUNNING      = "running"
    QUARANTINED  = "quarantined"
    SNAPSHOTTED  = "snapshotted"
    FROZEN       = "frozen"
    DESTROYED    = "destroyed"
    FAILED       = "failed"
```

### SnapshotRef: forensic chain support

```python
@dataclass(frozen=True)
class SnapshotRef:
    available: bool
    snapshot_id: str | None = None
    reason: str | None = None
    integrity_hash: str | None = None        # SHA256 of snapshot content
    snapshot_chain_parent: str | None = None # parent snapshot_id for chains
    snapshot_reason: str | None = None       # MANUAL / QUARANTINE / EMERGENCY / SCHEDULED
```

### ExecutionContext: correlation IDs

Add new dataclass — passed through `execute_isolated()` and stored on `ExecutionResult`:

```python
@dataclass
class ExecutionContext:
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    trace_id: str | None = None
    preserve_forensics: bool = False  # if True, do not destroy runtime on quarantine
```

### RuntimeHealthStats: per-runtime adaptive scoring

```python
@dataclass
class RuntimeHealthStats:
    runtime_id: str
    health_score: float = 100.0   # 0–100
    stability_score: float = 100.0
    anomaly_score: float = 0.0
    failure_rate: float = 0.0     # rolling failures / total executions
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

---

## Task 2 — CapabilitySnapshot + Detector

### Extended CapabilitySnapshot

```python
@dataclass(frozen=True)
class CapabilitySnapshot:
    # ... existing fields ...
    cache_health_score: float = 100.0         # 0–100, degrades if probes fail
    cache_source: str = "startup_probe"       # startup_probe | manual_refresh | background_healthcheck
    cache_generation: int = 0                 # increments on each refresh
```

### Background health monitoring hook

Add to `IsolationCapabilityDetector.__init__`:

```python
self._background_monitor_enabled: bool = False  # stub — future activation

def enable_background_monitoring(self, interval_seconds: int = 60) -> None:
    """
    Future: starts a daemon thread that re-probes on capability drift
    (Docker restart, KVM loss, WSL shutdown). Currently a no-op stub.
    Set self._background_monitor_enabled = True and spawn thread here.
    """
    self._background_monitor_enabled = True
    # TODO Plan C: implement drift detection thread
```

---

## Task 3 — IsolationStrategyManager

### Extended `select_tier()` signature

```python
def select_tier(
    self,
    snapshot: CapabilitySnapshot,
    policy: IsolationPolicy,
    requested_tier: IsolationTier | None,
    min_security_score: int = 0,
    required_capabilities: set[str] | None = None,
    preferred_runtime_types: list[str] | None = None,   # NEW: prefer these if tie
    forbidden_runtime_types: list[str] | None = None,   # NEW: never select these
    preferred_capabilities: set[str] | None = None,     # NEW: soft preference, not hard filter
) -> tuple[IsolationTier, list[IsolationTier], dict[str, str]]:
```

`forbidden_runtime_types` filters tiers whose `runtime_type` matches before any other logic.
`preferred_runtime_types` re-orders the candidate list to prefer matching tiers (doesn't exclude).
`preferred_capabilities` has no effect on selection today — stored in rejection_reasons for telemetry.

---

## Task 4 — NegotiationResult

### Extended fields

```python
@dataclass
class NegotiationResult:
    # ... existing fields ...
    negotiation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    decision_entropy: float = 0.0        # 0 = only one viable option, 1 = many equally good
    selection_confidence: float = 1.0    # 0–1, lower when many rejections occurred
    runtime_stability_estimate: float = 1.0  # future: fed by RuntimeHealthStats
    preferred_runtime_types: list[str] = field(default_factory=list)
    forbidden_runtime_types: list[str] = field(default_factory=list)
    degradation_telemetry: dict = field(default_factory=dict)
    # degradation_telemetry = {
    #   "original_requested": "FIRECRACKER",
    #   "degradation_path": ["FIRECRACKER", "QEMU", "DOCKER_HARDENED"],
    #   "unavailable_capabilities": ["supports_nested_isolation"],
    #   "host_state": {"has_kvm": False, "has_docker": True},
    # }
```

`decision_entropy` = `log2(len(viable_candidates)) / log2(5)` clamped to [0, 1].
`selection_confidence` = `1 - (len(rejections) / len(candidates))`.

---

## Task 5 — ProcessJailDriver

### Hardened execute()

```python
async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload,
                  ctx: ExecutionContext | None = None) -> ExecutionResult:
    import asyncio, time, signal, os
    MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MB stdout limit

    start = time.monotonic()
    workspace = _get_handle_state(handle.runtime_id, "workspace", ".")
    cmd = payload.command or (f"python -c {repr(payload.code)}" if payload.code else "")
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )
    _set_handle_state(handle.runtime_id, "pid", proc.pid)
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=payload.timeout_seconds
        )
        # Enforce output size limit
        output = stdout[:MAX_OUTPUT_BYTES].decode(errors="replace") if stdout else ""
        error_out = stderr[:MAX_OUTPUT_BYTES].decode(errors="replace") if stderr else None
        code = proc.returncode or 0
    except asyncio.TimeoutError:
        # Kill entire process tree
        await _kill_process_tree(proc.pid)
        await proc.wait()
        output, error_out, code = "", "timeout", 124
    except Exception as e:
        await _kill_process_tree(proc.pid)
        output, error_out, code = "", str(e), 1
    return ExecutionResult(
        success=code == 0, output=output, error=error_out,
        exit_code=code, runtime_id=handle.runtime_id,
        tier_used=IsolationTier.PROCESS_JAIL,
        duration_ms=int((time.monotonic() - start) * 1000),
        execution_id=ctx.execution_id if ctx else str(uuid.uuid4()),
        correlation_id=ctx.correlation_id if ctx else None,
    )


async def _kill_process_tree(pid: int) -> None:
    """Kill pid and all its children."""
    import platform, signal
    try:
        if platform.system().lower() == "windows":
            import subprocess
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True)
        else:
            import os, signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            import os
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
```

---

## Task 6 — SandboxDriver

### Health validation + stale cleanup

```python
async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
    from core.sandbox.sandbox_manager import get_sandbox_manager
    mgr = get_sandbox_manager()
    # Validate sandbox manager health before creating
    try:
        health = mgr.get_health_status() if hasattr(mgr, "get_health_status") else {"healthy": True}
        if not health.get("healthy", True):
            raise RuntimeError("SandboxManager health check failed")
    except AttributeError:
        pass  # older SandboxManager without health check
    result = mgr.create_sandbox(agent_id=config.agent_id, mode="STRICT_ISOLATION")
    handle = RuntimeHandle(
        runtime_id=str(uuid.uuid4()), runtime_type="sandbox",
        tier=IsolationTier.SANDBOX, created_at=datetime.utcnow(),
    )
    _set_handle_state(handle.runtime_id, "sandbox_id", result["sandbox_id"])
    _set_handle_state(handle.runtime_id, "agent_id", config.agent_id)
    return handle

async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
    from core.sandbox.sandbox_manager import get_sandbox_manager
    sandbox_id = _get_handle_state(handle.runtime_id, "sandbox_id")
    if sandbox_id:
        try:
            get_sandbox_manager().quarantine_sandbox(sandbox_id, reason)
        except Exception:
            pass
    # Escalate to permission manager
    agent_id = _get_handle_state(handle.runtime_id, "agent_id", "unknown")
    try:
        from core.security.permission_manager import get_permission_manager
        get_permission_manager().isolate_agent(agent_id, reason)
    except Exception:
        pass
```

---

## Task 7 — DockerHardenedDriver

### Hardened run config

Replace `_HARDENED_RUN_KWARGS` with:

```python
_HARDENED_RUN_KWARGS = dict(
    read_only=False,           # overlay writable; base image readonly via bind mounts
    network_mode="none",
    mem_limit="512m",
    mem_swappiness=0,
    cpu_period=100_000,
    cpu_quota=50_000,
    pids_limit=64,
    security_opt=[
        "no-new-privileges:true",
        "seccomp=unconfined",  # replace with custom profile in Plan B hardening
    ],
    cap_drop=["ALL"],
    tmpfs={"/tmp": "size=64m,noexec,nosuid,nodev"},   # tmpfs for /tmp
    userns_mode="host",        # override in production with user namespace remap
    init=False,                # no init process — reduces surface
    detach=True,
    remove=False,
)
```

### Runtime verification before execute

```python
def _verify_daemon(self) -> dict:
    """Returns daemon health. Triggers fallback if critical checks fail."""
    try:
        client = self._client()
        info = client.info()
        return {
            "healthy": True,
            "runtime": info.get("DefaultRuntime", "runc"),
            "cgroup_driver": info.get("CgroupDriver"),
            "security_options": info.get("SecurityOptions", []),
            "seccomp_enabled": any("seccomp" in o for o in info.get("SecurityOptions", [])),
        }
    except Exception as e:
        return {"healthy": False, "error": str(e)}

async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
    health = self._verify_daemon()
    if not health["healthy"]:
        raise RuntimeError(f"Docker daemon unhealthy: {health.get('error')}")
    # ... rest of existing create_runtime ...
```

---

## Task 8 — IsolationAuditLogger

### Canonical JSON hash chain

Replace the `raw = f"..."` string in `log_event` with:

```python
import json

def _canonical(self, data: dict) -> str:
    """Deterministic JSON — sorted keys, no whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=str)

# In log_event, replace raw string with:
event_dict = {
    "event_id": event_id,
    "vm_id": vm_id,
    "event_type": event_type,
    "severity": severity,
    "description": description,
    "metadata": metadata,
    "timestamp": now,
    "prev_hash": self._prev_hash or "",
}
raw = self._canonical(event_dict)
row_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Use the same `_canonical()` in `verify_chain()` to recompute hashes.

### Future export hooks (stubs)

```python
def export_forensic_bundle(self, vm_id: str, output_path: Path) -> None:
    """Future: exports all events for vm_id as a signed forensic bundle."""
    raise NotImplementedError("forensic_bundle export — Plan C")

def sync_to_siem(self, endpoint: str) -> None:
    """Future: pushes audit trail to external SIEM connector."""
    raise NotImplementedError("SIEM sync — Plan C")
```

---

## Task 9 — UnifiedIsolationRuntime

### Stays thin — delegate everything

Key rule: if any method grows beyond ~15 lines of logic, extract to a helper module.
`UnifiedIsolationRuntime` must only: negotiate → delegate → audit.

### Correlation IDs on every execution

```python
async def execute_isolated(
    self,
    payload: ExecutionPayload,
    policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
    ctx: ExecutionContext | None = None,   # NEW: caller can supply correlation IDs
    ...
) -> ExecutionResult:
    ctx = ctx or ExecutionContext()  # auto-generate if not supplied
    # Pass ctx through to driver.execute()
    # Store ctx.execution_id + ctx.correlation_id in audit log
```

### Degradation telemetry logging

After negotiation, if `negotiation.fallback_level > 0`:

```python
self._logger.log_event(
    vm_id="system",
    event_type="DEGRADATION",
    severity="WARNING",
    description=f"Requested {negotiation.requested_tier}, got {negotiation.actual_tier}",
    metadata={
        "original_requested": negotiation.requested_tier.name if negotiation.requested_tier else None,
        "actual": negotiation.actual_tier.name,
        "fallback_level": negotiation.fallback_level,
        "fallback_chain": [t.name for t in negotiation.fallback_chain],
        "policy": negotiation.policy.value,
    },
    correlation_id=ctx.correlation_id,
    origin_component="unified_isolation_runtime",
)
```

### Forensic preservation mode

```python
async def _handle_quarantine(
    self,
    driver: IsolationDriver,
    handle: RuntimeHandle,
    reason: str,
    ctx: ExecutionContext,
) -> None:
    await driver.quarantine(handle, reason)
    if ctx.preserve_forensics:
        # Snapshot before any cleanup
        ref = await driver.snapshot(handle)
        self._logger.log_event(
            vm_id=handle.runtime_id,
            event_type="FORENSIC_PRESERVED",
            severity="INFO",
            description=f"Snapshot preserved: {ref.snapshot_id}",
            metadata={"snapshot_id": ref.snapshot_id, "reason": reason},
            correlation_id=ctx.correlation_id,
        )
        # Do NOT destroy — leave for investigation
        return
    await driver.destroy(handle)
```

### Remote execution hook (stub)

```python
async def execute_on_remote_node(
    self,
    node_id: str,
    payload: ExecutionPayload,
    ctx: ExecutionContext | None = None,
) -> ExecutionResult:
    """Future: routes to a remote Linux isolation node."""
    raise NotImplementedError("remote_execution — Plan C")
```

---

## ExecutionResult: extended fields

Add to `ExecutionResult` in `isolation_driver.py`:

```python
@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: str | None
    exit_code: int
    runtime_id: str
    tier_used: IsolationTier
    duration_ms: int
    negotiation: Any = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    trace_id: str | None = None
    runtime_state: RuntimeLifecycleState = RuntimeLifecycleState.DESTROYED
    health_stats: Any = None  # RuntimeHealthStats, set post-execution
```

---

## Dependency Direction — Enforcement Rules

These rules are non-negotiable. Add as module-level comments to each file.

```python
# isolation_driver.py    — zero imports from this project
# isolation_capability_detector.py — imports: isolation_driver only
# isolation_strategy_manager.py   — imports: isolation_driver, isolation_capability_detector
# isolation_negotiator.py         — imports: isolation_driver, isolation_capability_detector, isolation_strategy_manager
# isolation_audit_logger.py       — imports: isolation_driver, isolation_negotiator (TYPE_CHECKING only)
# unified_isolation_runtime.py    — imports: all of the above + drivers
# drivers/*.py                    — imports: isolation_driver only (NO negotiator, NO audit_logger)
```

Drivers must not import from `isolation_negotiator` or `isolation_audit_logger`.
The runtime is the only layer that crosses all modules.
