# VM Isolation Layer + Isolation Abstraction Layer — Design Spec
**Date:** 2026-05-07
**Status:** Approved — ready for implementation
**Phase:** Nexus BNL — VM Isolation Phase

---

## 1. Goals

Create a hypervisor-grade isolation layer for Nexus BNL that can safely execute untrusted agents, downloaded tools, autonomous architects, and behavioral simulations with drastically reduced host-compromise risk.

**Primary objectives:**
- Layered degradation: best available isolation runs automatically (Firecracker → QEMU → Docker → Sandbox → ProcessJail)
- Unified interface: callers never know which tier ran
- Future-ready: Firecracker/QEMU activate automatically on Linux with zero API changes
- Forensic-first: every VM session produces a full tamper-evident audit trail
- Resilient emergency response: escape/ransomware/abuse triggers a multi-step pipeline that cannot be silenced by a single failure

---

## 2. Two New Folders — Strict Dependency Direction

```
core/
├── isolation_abstraction/    ← decision intelligence (new)
└── vm_isolation/             ← execution providers (new)
```

**Dependency rule (non-negotiable, no exceptions):**
```
isolation_abstraction  →  vm_isolation
isolation_abstraction  →  container_security
isolation_abstraction  →  sandbox
isolation_abstraction  →  isolation

vm_isolation           →  (its own internals only)
sandbox                ✗  isolation_abstraction
isolation              ✗  isolation_abstraction
container_security     ✗  isolation_abstraction
```

No circular imports. `vm_isolation/` is not a god-module. The abstraction layer is the only cross-module importer.

### Tier Registry

| Tier | Driver | Availability Check | Fallback |
|------|--------|--------------------|----------|
| 1 | `FirecrackerDriver` | `/usr/bin/firecracker` + `/dev/kvm` | Tier 2 |
| 2 | `QemuDriver` | `qemu-system-x86_64` + `/dev/kvm` | Tier 3 |
| 3 | `DockerHardenedDriver` | `docker info` succeeds | Tier 4 |
| 4 | `SandboxDriver` | Always available | Tier 5 |
| 5 | `ProcessJailDriver` | Always available | Block |

Tiers 4–5 are always available. Nexus is never left without isolation capability.

On Windows 11 today: Tiers 1–2 register unavailable at startup, Tiers 3–5 run normally.
On Linux + KVM: Tiers 1–2 activate automatically, zero API changes.

---

## 3. Isolation Abstraction Layer — `core/isolation_abstraction/`

### 3.1 Files

```
isolation_abstraction/
├── __init__.py
├── isolation_driver.py              # Abstract base (Protocol + ABC hybrid)
├── isolation_capability_detector.py
├── isolation_negotiator.py
├── isolation_strategy_manager.py
├── unified_isolation_runtime.py     # Public API: execute_isolated()
└── isolation_audit_logger.py
```

### 3.2 `isolation_driver.py` — Protocol + ABC Hybrid

```python
class IsolationDriver(ABC):
    @property
    @abstractmethod
    def tier(self) -> IsolationTier: ...

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilities: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle: ...

    @abstractmethod
    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult: ...

    @abstractmethod
    async def destroy(self, handle: RuntimeHandle) -> None: ...

    @abstractmethod
    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef: ...
    # Returns SnapshotRef(available=False) if unsupported — never raises

    @abstractmethod
    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None: ...
```

`IsolationTier` is `IntEnum` — tiers are comparable (`tier1 < tier3`). Protocol typing enables structural duck-typing for mocks.

### 3.3 `DriverCapabilities` — frozen metadata per driver

```python
@dataclass(frozen=True)
class DriverCapabilities:
    tier: IsolationTier
    # Core isolation
    supports_snapshots: bool
    supports_memory_snapshots: bool
    supports_hot_snapshot: bool
    supports_incremental_snapshots: bool
    supports_behavioral_lab: bool
    supports_network_isolation: bool
    supports_filesystem_isolation: bool
    supports_forensics: bool
    supports_live_forensics: bool
    supports_nested_isolation: bool
    supports_readonly_rootfs: bool
    # Advanced / future
    supports_secure_boot: bool
    supports_tpm_emulation: bool
    supports_virtualized_gpu: bool
    supports_gpu_isolation: bool
    supports_network_deception: bool
    supports_runtime_migration: bool
    supports_attestation: bool
    supports_remote_nodes: bool
    supports_remote_execution: bool
    max_concurrent_runtimes: int      # 0 = unlimited
```

`DriverCapabilities` is immutable (`frozen=True`). The `TIER_CAPABILITIES` dict maps each `IsolationTier` to its static profile. Used by `IsolationNegotiator` to filter drivers by required capabilities without any conditional logic.

### 3.4 `CapabilitySnapshot` — immutable host probe result

```python
@dataclass(frozen=True)
class CapabilitySnapshot:
    has_firecracker: bool
    has_qemu: bool
    has_kvm: bool
    has_docker: bool
    has_wsl2: bool
    has_nested_virtualization: bool
    host_os: Literal["linux", "windows", "macos", "unknown"]
    docker_runtime: str | None        # "docker" | "containerd" | "podman"
    virtualization_type: str | None   # "kvm" | "hyperv" | "wsl2" | "qemu" | "firecracker"
    last_refresh_reason: str | None   # "startup" | "manual_refresh" | "docker_restart" | "healthcheck_failure"
    available_tiers: frozenset[IsolationTier]
    detected_at: datetime
```

`available_tiers` is the computed single source of truth. Cached at startup, refreshable on demand.

```python
class IsolationCapabilityDetector:
    def detect(self) -> CapabilitySnapshot: ...          # cached, thread-safe
    def refresh_capabilities(
        self,
        reason: str,
        requester: str,
        cooldown_seconds: int = 30,                      # rate-limits refresh calls
    ) -> CapabilitySnapshot: ...
    # refresh is rate-limited, audit-trailed, permission-validated
```

### 3.5 `NegotiationResult` — full reasoning record

```python
@dataclass(frozen=True)
class NegotiationResult:
    # Selection outcome
    requested_tier: IsolationTier
    actual_tier: IsolationTier
    policy: IsolationPolicy
    reason: str

    # Execution context
    host_os: str
    fallback_level: int
    fallback_chain: tuple[IsolationTier, ...]

    # Driver quality
    driver_capabilities: DriverCapabilities
    security_score: int                    # 0–100, static per tier
    risk_adjusted_score: int               # security_score adjusted for anomalies, QEMU complexity
    forensic_support: bool
    behavioral_support: bool

    # Full reasoning trail
    candidate_drivers: tuple[IsolationTier, ...]
    rejection_reasons: dict[str, str]      # tier_name → reason
    capability_mismatches: dict[str, list[str]]
    policy_rejections: dict[str, str]

    # Execution health (post-execution enrichment)
    execution_duration_ms: int | None
    actual_runtime_health: str | None
    post_execution_anomalies: list[str]
    degradation_impact: str | None

    # Future-readiness
    remote_execution_ready: bool
    degradation_acceptable: bool
```

`risk_adjusted_score` differs from `security_score`:
- QEMU gets automatic `-5` adjustment for higher attack surface
- Behavioral Lab anomalies reduce score dynamically
- Honeytoken/exfiltration signals from BehavioralLab increase adjustment

Base scores: Firecracker=95, QEMU=87, Docker=70, Sandbox=40, ProcessJail=20.

### 3.6 `IsolationPolicy` — four named policies

| Policy | Behavior |
|--------|----------|
| `BEST_AVAILABLE` | Highest tier in `available_tiers`. Never blocks. |
| `SAFE_DEGRADATION` | Accept tier ≥ 3 (Docker). Block if only Tier 4–5 and network isolation required. |
| `STRICT_ISOLATION` | Block unless Tier 1 or 2 available. For malware research, untrusted external agents. |
| `NO_FALLBACK` | Exact requested tier or raise `IsolationUnavailableError`. |

### 3.7 `RuntimeHandle` — fully opaque to callers

```python
@dataclass(frozen=True)
class RuntimeHandle:
    runtime_id: str           # UUID, stable. This is the only field callers use.
    runtime_type: str         # "firecracker" | "qemu" | "docker" | "sandbox" | "jail"
    tier: IsolationTier
    created_at: datetime
    opaque_metadata: dict     # internal only — drivers use _get/_update helpers, callers never access

# Internal helpers — not part of public API
def _get_runtime_internal_state(handle: RuntimeHandle) -> dict: ...
def _update_runtime_internal_state(handle: RuntimeHandle, updates: dict) -> RuntimeHandle: ...
```

### 3.8 `unified_isolation_runtime.py` — the only public API

```python
class UnifiedIsolationRuntime:
    """SINGLETON. All isolation flows through here."""

    async def execute_isolated(
        self,
        payload: ExecutionPayload,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        required_tier: IsolationTier | None = None,
        minimum_security_score: int = 0,
        requires_forensics: bool = False,
        requires_network_isolation: bool = False,
        requires_behavioral_lab: bool = False,
        requires_live_forensics: bool = False,
    ) -> ExecutionResult: ...

    async def create_isolated_runtime(
        self,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        **requirements,
    ) -> RuntimeHandle: ...

    def refresh_capabilities(self, reason: str = "manual_refresh") -> CapabilitySnapshot: ...

    def get_negotiation_history(self, limit: int = 100) -> list[NegotiationResult]: ...

def get_unified_runtime() -> UnifiedIsolationRuntime: ...
```

No caller imports from `vm_isolation/`, `sandbox/`, or `isolation/` for execution. All paths flow through `get_unified_runtime()`.

---

## 4. VM Isolation Layer — `core/vm_isolation/`

### 4.1 Files

```
vm_isolation/
├── __init__.py
├── vm_manager.py              # Meta-orchestrator SINGLETON
├── microvm_manager.py
├── firecracker_runtime.py     # Tier 1 driver
├── qemu_runtime.py            # Tier 2 driver
├── vm_policy_engine.py
├── vm_snapshot_manager.py
├── vm_network_isolation.py
├── vm_filesystem_guard.py
├── vm_resource_limiter.py
├── vm_behavior_monitor.py
├── vm_forensics.py
├── vm_quarantine.py
├── vm_escape_detector.py
├── hypervisor_guardian.py
├── disposable_vm_pool.py
└── vm_audit_logger.py
```

### 4.2 `vm_manager.py` — meta-orchestrator

Implements `IsolationDriver` for Tiers 1–2. Also maintains runtime topology, parent/child relationships, disposable pool coordination, and emergency quarantine orchestration. Prepared for distributed orchestration.

```python
class VMManager:
    """SINGLETON. Meta-orchestrator for all VM-tier runtimes."""

    def is_available(self) -> bool: ...

    @property
    def capabilities(self) -> DriverCapabilities: ...
    # Returns FIRECRACKER_CAPABILITIES if Firecracker available, else QEMU_CAPABILITIES

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle: ...
    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult: ...
    async def destroy(self, handle: RuntimeHandle) -> None: ...
    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef: ...
    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None: ...

    # Topology
    def get_runtime_topology(self) -> dict: ...             # parent/child graph
    def get_runtime_lineage(self, runtime_id: str) -> list: # full lifecycle chain

def get_vm_manager() -> VMManager: ...
```

### 4.3 `firecracker_runtime.py` + `microvm_manager.py`

**Boot flow:**
```
FirecrackerRuntime.launch(config)
  → validate jailer config
  → validate rootfs SHA256
  → spawn: firecracker --api-sock /run/fc-{id}.sock --config-file /tmp/fc-{id}.json
  → PUT /machine-config  {vcpu_count, mem_size_mib}
  → PUT /boot-source     {kernel_image_path, boot_args (immutable, hardcoded)}
  → PUT /drives/rootfs   {path_on_host, is_read_only=True, overlay=disposable}
  → PUT /network-interfaces {tap_dev, isolated_bridge}
  → PUT /actions {action_type: "InstanceStart"}
  → validate microVM integrity post-boot
  → return RuntimeHandle
```

**Hardening applied:**
- Seccomp hardened profile applied to jailer process
- Readonly rootfs enforcement at API level
- Immutable kernel args (no override allowed)
- Forbidden device validation (no `/dev/kvm` passthrough inside VM)
- MicroVM integrity check after boot (hash validation)

**QEMU risk classification:**
`QemuRuntime` sets `risk_adjustment = "higher_attack_surface"` in its capabilities. The negotiator applies a `-5` penalty to `risk_adjusted_score` for all QEMU sessions, reflected in forensics and dashboard.

### 4.4 `vm_policy_engine.py` — versioned immutable policies

```python
class VMProfile(Enum):
    SAFE_VM        = "safe_vm"
    RESTRICTED_VM  = "restricted_vm"
    QUARANTINE_VM  = "quarantine_vm"
    LOCKDOWN_VM    = "lockdown_vm"

@dataclass(frozen=True)
class VMPolicy:
    profile: VMProfile
    allow_host_mounts: bool           # always False for QUARANTINE/LOCKDOWN
    allow_outbound_network: bool
    allow_shared_memory: bool         # always False
    readonly_boot_layer: bool         # always True
    disposable_disk: bool             # always True
    encrypted_runtime_storage: bool
    max_cpu_percent: float
    max_ram_mb: int
    max_runtime_seconds: int
    auto_destroy_on_exit: bool
    minimum_security_score: int       # SAFE_VM=60, LOCKDOWN_VM=90
    minimum_required_capabilities: frozenset[str]
    allowed_runtime_types: frozenset[str]
    forbidden_runtime_types: frozenset[str]
    policy_version: int
    policy_signature: str | None      # future: signed policy updates
```

**Policy versioning rule:** Policies are never edited in place. Any change creates a new version row in `vm_policies` with `superseded_at` set on the old version. Previous versions are preserved for forensic integrity. Future: `policy_signature` field holds cryptographic signature for signed updates.

### 4.5 `vm_network_isolation.py`

Creates isolated network bridges per VM. Connects to BehavioralLab's fake internet router.

```
VM ─── tap0 ─── isolated bridge ─── fake DNS ─── fake internet router
                                  └── outbound filter
                                  └── traffic logger → vm_forensics
                                  └── deception router (honeytokens)
```

Deception features:
- **Fake latency injection** — configurable per session
- **Fake packet loss** — simulates unreliable links
- **Fake enterprise routing** — internal corporate topology simulation
- **DNS deception profiles** — responds with fake internal domains
- **Outbound throttling** — limits exfiltration throughput
- **Traffic replay simulation** — simulates real enterprise noise

Integration: `vm_network_isolation.attach_fake_internet(bridge, get_behavioral_lab().get_fake_internet_router())`

### 4.6 `vm_filesystem_guard.py`

Immutable base + disposable overlay per VM:

```
/vm-rootfs/base-image.ext4    (readonly, SHA256-pinned)
         + overlay.qcow2      (disposable, destroyed on exit)
         + forensic-copy.tar  (captured on quarantine/escape)
```

Advanced detection:
- **Filesystem entropy analysis** — detect encryption spikes
- **Ransomware write pattern detection** — mass overwrites in rapid succession
- **Mass rename detection** — bulk extension changes
- **Suspicious encryption pattern detection** — file header corruption signatures
- **Immutable path monitoring** — inotify on critical paths

If ransomware/destruction detected: immediate freeze + forensic snapshot, no grace period.

### 4.7 `vm_resource_limiter.py`

```python
@dataclass
class VMResourceLimits:
    max_vcpus: int
    max_ram_mb: int
    max_disk_mb: int
    max_network_kbps: int
    max_processes: int
    max_runtime_seconds: int
```

Anomaly detection (from outside the VM via cgroups):
- **Burst detection** — sustained CPU spike above threshold
- **Crypto mining heuristics** — high CPU + low memory + specific instruction patterns
- **Abnormal IO spikes** — random read pattern + high throughput
- **Runaway thread detection** — process count explosion
- **Memory pressure anomaly** — RSS growth beyond expected profile

Limits enforced via cgroups v2 (Linux) or Docker resource constraints (Windows Tier 3). Limits hold even if the VM OS is compromised.

### 4.8 `vm_escape_detector.py`

| Signal | Detection Method |
|--------|-----------------|
| Hypervisor probing | Unusual hypercall patterns via KVM perf counters |
| `/dev/kvm` access inside VM | inotify on host KVM device |
| Unexpected host mounts | Mount namespace monitoring from host |
| Docker socket probe | inotify on `/var/run/docker.sock` |
| Pivot root / namespace abuse | seccomp audit logs |
| VM fingerprinting | CPUID leaf abuse in KVM log |
| Memory balloon abuse | Sudden balloon inflation requests |
| Side-channel probing | Timing anomaly patterns (cache flush sequences) |
| Speculative execution probing | Known Spectre-class instruction sequences |
| Suspicious device enumeration | Unusual PCI/virtio enumeration frequency |
| Hypervisor API abuse | Excessive or malformed API socket calls |
| Timing anomalies | Statistical deviation from baseline latency |

On any escape signal → triggers Emergency VM Response Pipeline.

### 4.9 `hypervisor_guardian.py` — VM security brain

Daemon thread (mirrors `RuntimeGuardian` pattern). Monitoring loop every 5s:

```
poll active VMs
→ resource limits check (vm_resource_limiter)
→ policy compliance check (vm_policy_engine)
→ escape signal check (vm_escape_detector)
→ filesystem integrity check (vm_filesystem_guard)
→ behavioral metrics update (vm_behavior_monitor)
→ flush events to vm_audit_logger (hash-chained)

On violation:
  WARN     → log + alert
  ERROR    → freeze VM + forensic snapshot
  CRITICAL → Emergency VM Response Pipeline
```

Cross-layer alert coordination:
- Notifies `isolation_abstraction` to mark `runtime_id` as QUARANTINED
- Notifies `security_layer` → `policy_engine`
- Notifies `ast_security_engine` to flag `agent_id`
- Notifies `recovery_layer` → rollback readiness

Future: distributed alert propagation to remote nodes.

### 4.10 `disposable_vm_pool.py` — adaptive pre-warmed pool

```python
class DisposableVMPool:
    async def acquire(self, profile: VMProfile) -> RuntimeHandle: ...
    # Returns immediately; starts warming replacement in background
    async def release(self, handle: RuntimeHandle) -> None: ...
    # Always destroys — never reuses
    def pool_status(self) -> dict[VMProfile, int]: ...
```

Adaptive features:
- **Adaptive pool sizing** — grows pool under load, shrinks at idle
- **Runtime prewarming heuristics** — tracks usage patterns to warm the right profiles
- **Automatic unhealthy VM recycling** — health-failed VMs replaced without intervention
- **Load-aware warm pools** — warm count scales with active agent count
- **Emergency quarantine pools** — dedicated warm QUARANTINE_VM instances ready

On Windows (no Firecracker): pool pre-warms Docker containers via Tier 3 driver. Same API.

### 4.11 `vm_forensics.py`

```python
@dataclass
class VMForensicRecord:
    forensic_id: str
    vm_id: str
    session_id: str
    timeline: list[ForensicEvent]
    process_tree: dict
    network_flows: list[NetworkFlow]
    filesystem_diff: list[FSChange]
    memory_hashes: dict | None
    memory_metadata: dict | None
    runtime_entropy_score: float
    suspicious_api_sequences: list[str]
    behavioral_anomaly_score: float
    cross_runtime_correlations: list[CorrelationRef]
    # Attack graph reconstruction
    attack_graph: dict | None
    repeated_behavioral_fingerprints: list[str]
    shared_anomaly_signatures: list[str]
    campaign_correlation_id: str | None
    # Alert trail
    escape_signals: list[EscapeSignal]
    hypervisor_alerts: list[Alert]
    risk_score: int
    preserved_at: datetime
    trigger: str    # ESCAPE / QUARANTINE / MANUAL / SCHEDULED
```

`cross_runtime_correlations` links sessions by shared anomaly signatures for campaign detection. Recidivists and coordinated agents are identified via `repeated_behavioral_fingerprints`.

### 4.12 `vm_audit_logger.py`

Append-only, hash-chained. Same pattern as `ImmutableAuditLog` in `recovery/`:

```python
class VMAuditLogger:
    def log(self, event_type: str, severity: str, vm_id: str,
            description: str, metadata: dict,
            correlation_id: str | None = None,
            origin_layer: str | None = None,
            origin_component: str | None = None) -> None:
        # row_hash = SHA256(all fields + prev_hash)
        # Tamper detection: verify chain on read
```

---

## 5. Emergency VM Response Pipeline

Triggered by: escape attempt, ransomware detection, host probing, hypervisor abuse, critical resource anomaly.

Owned by `HypervisorGuardian`. All steps write hash-chained rows to `vm_events`. Single-step failure never halts the pipeline.

```
Step 1: vm_quarantine.freeze(vm_id)
  → halt vCPUs via hypervisor API
  → deny all new syscalls from VM

Step 2: vm_snapshot_manager.emergency_snapshot(vm_id)
  → capture memory + disk overlay atomically
  → compute manifest_hash

Step 3: vm_forensics.capture_full_timeline(vm_id)
  → process tree, network flows, filesystem diff
  → entropy score, behavioral_anomaly_score, cross_runtime_correlations

Step 4: VERIFICATION GATE
  → verify snapshot integrity (manifest_hash check)
  → verify forensic preservation (record completeness check)
  → verify quarantine enforcement (VM state == FROZEN)
  → record partial_failure_tracking:
      {"snapshot": "success|failed", "forensics": "success|failed", "quarantine": "success|failed"}
  → pipeline continues regardless of individual step failures

Step 5: vm_quarantine.full_quarantine(vm_id, reason)
  → move to QUARANTINE_VM profile
  → revoke all outbound network
  → write CRITICAL event (hash-chained)

Step 6: hypervisor_guardian.broadcast_cross_layer_alert(vm_id, severity=CRITICAL)
  → isolation_abstraction: mark runtime_id QUARANTINED
  → security_layer: policy_engine record breach + agent flag
  → ast_security_engine: flag agent_id
  → behavioral_lab: increment risk_adjusted_score (honeytoken/exfiltration correlation)

Step 7: recovery_layer.prepare_emergency_restore()
  → restore_manager.mark_ready(checkpoint)
  → rollback_engine.set_alert_state()

Step 8 (stub, future): host_protection_escalation()
  → hardening_layer: seccomp escalation hook
  → hardening_layer: host lockdown hook
  → hardening_layer: Docker daemon protection hook
```

---

## 6. Database Schema — `data/nexus_vm_isolation.db`

### `virtual_machines`
```sql
CREATE TABLE virtual_machines (
    vm_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_tier TEXT,
    fallback_level INTEGER DEFAULT 0,
    security_score INTEGER,
    risk_adjusted_score INTEGER,
    node_id TEXT,               -- future: distributed nodes
    cluster_id TEXT,            -- future: cluster membership
    remote_runtime BOOLEAN DEFAULT FALSE,
    created_at TEXT,
    destroyed_at TEXT,
    agent_id TEXT
);
```

### `vm_sessions`
```sql
CREATE TABLE vm_sessions (
    session_id TEXT PRIMARY KEY,
    vm_id TEXT,
    requested_tier TEXT,
    actual_tier TEXT,
    policy TEXT,
    negotiation_result TEXT,        -- JSON: full NegotiationResult
    candidate_drivers TEXT,         -- JSON
    rejection_reasons TEXT,         -- JSON
    capability_mismatches TEXT,     -- JSON
    policy_rejections TEXT,         -- JSON
    execution_duration_ms INTEGER,
    actual_runtime_health TEXT,
    post_execution_anomalies TEXT,  -- JSON
    degradation_impact TEXT,
    started_at TEXT,
    ended_at TEXT,
    exit_reason TEXT
);
```

### `vm_events`
```sql
CREATE TABLE vm_events (
    event_id TEXT PRIMARY KEY,
    vm_id TEXT,
    event_type TEXT,
    severity TEXT,
    description TEXT,
    metadata TEXT,
    correlation_id TEXT,            -- cross-layer correlation
    runtime_chain_id TEXT,          -- runtime lineage chain
    origin_layer TEXT,              -- "vm_isolation" | "hardening" | "behavioral_lab" etc.
    origin_component TEXT,          -- "vm_escape_detector" | "hypervisor_guardian" etc.
    timestamp TEXT,
    row_hash TEXT,
    prev_hash TEXT
);
```

### `vm_escape_attempts`
```sql
CREATE TABLE vm_escape_attempts (
    attempt_id TEXT PRIMARY KEY,
    vm_id TEXT,
    signal_type TEXT,
    detection_method TEXT,
    evidence TEXT,                  -- JSON
    side_channel_indicators TEXT,   -- JSON: timing anomalies, speculative probing
    vm_fingerprinting_detected BOOLEAN,
    hypervisor_api_abuse BOOLEAN,
    timing_anomaly_detected BOOLEAN,
    severity TEXT,
    response_action TEXT,
    forensic_snapshot_id TEXT,
    partial_failure_tracking TEXT,  -- JSON: pipeline step outcomes
    timestamp TEXT
);
```

### `vm_policies`
```sql
CREATE TABLE vm_policies (
    policy_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    definition TEXT NOT NULL,               -- JSON: full VMPolicy
    minimum_security_score INTEGER,
    allowed_runtime_types TEXT,             -- JSON array
    forbidden_runtime_types TEXT,           -- JSON array
    minimum_required_capabilities TEXT,     -- JSON
    version INTEGER DEFAULT 1,
    signature TEXT,                         -- future: signed updates
    created_at TEXT,
    superseded_at TEXT                      -- NULL if current version
);
```

### `vm_forensics`
```sql
CREATE TABLE vm_forensics (
    forensic_id TEXT PRIMARY KEY,
    vm_id TEXT,
    session_id TEXT,
    timeline TEXT,                          -- JSON
    process_tree TEXT,                      -- JSON
    network_flows TEXT,                     -- JSON
    filesystem_diff TEXT,                   -- JSON
    memory_hashes TEXT,                     -- JSON
    runtime_entropy_score REAL,
    suspicious_api_sequences TEXT,          -- JSON
    behavioral_anomaly_score REAL,
    cross_runtime_correlations TEXT,        -- JSON
    attack_graph TEXT,                      -- JSON
    repeated_behavioral_fingerprints TEXT,  -- JSON
    shared_anomaly_signatures TEXT,         -- JSON
    campaign_correlation_id TEXT,
    memory_metadata TEXT,                   -- JSON
    escape_signals TEXT,                    -- JSON
    hypervisor_alerts TEXT,                 -- JSON
    risk_score INTEGER,
    preserved_at TEXT,
    trigger TEXT
);
```

### `vm_snapshots`
```sql
CREATE TABLE vm_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    vm_id TEXT,
    snapshot_type TEXT,             -- FULL / INCREMENTAL / HOT / MEMORY / EMERGENCY
    state_path TEXT,
    manifest_hash TEXT,
    parent_snapshot_id TEXT,        -- incremental chains
    is_secure_boot_verified BOOLEAN,
    tpm_measurement TEXT,           -- future: measured boot
    attestation_report TEXT,        -- future: remote attestation
    created_at TEXT,
    restored_at TEXT
);
```

### `vm_runtime_metrics`
```sql
CREATE TABLE vm_runtime_metrics (
    metric_id TEXT PRIMARY KEY,
    vm_id TEXT,
    cpu_percent REAL,
    ram_mb REAL,
    disk_io_kbps REAL,
    network_kbps REAL,
    process_count INTEGER,
    entropy_score REAL,
    crypto_mining_score REAL,
    burst_detected BOOLEAN,
    scheduler_latency_ms REAL,
    hypervisor_pressure_score REAL,
    isolation_stability_score REAL,
    anomaly_flags TEXT,             -- JSON
    timestamp TEXT
);
```

**Indexes:** `vm_id`, `session_id`, `timestamp`, `status`, `severity`, `signal_type`, `trigger`, `correlation_id`, `campaign_correlation_id` across all tables.

---

## 7. API Endpoints — `app/routes/vm_routes.py`

All endpoints registered in `nexus_bot.py`.

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/vm/create` | Rate-limited; requires permission check |
| `POST` | `/vm/destroy` | Requires permission check |
| `POST` | `/vm/execute` | Rate-limited; requires permission check |
| `GET`  | `/vm/list` | Active VMs: tier, profile, status, security_score |
| `GET`  | `/vm/forensics/{vm_id}` | Full VMForensicRecord |
| `GET`  | `/vm/threats` | Recent escape attempts + anomalies, paginated |
| `GET`  | `/vm/policies` | Current VMPolicy per profile (current version only) |
| `GET`  | `/vm/pool/status` | Warm count per profile, unhealthy, capacity |
| `GET`  | `/vm/capabilities` | Current CapabilitySnapshot |
| `POST` | `/vm/capabilities/refresh` | Rate-limited; cooldown enforced; audit-trailed |
| `GET`  | `/vm/negotiation/history` | Recent NegotiationResults with reasoning trail |
| `GET`  | `/vm/status` | HypervisorGuardian health, active VMs, last event |

Rate limiting applies to `/vm/create`, `/vm/execute`, `/vm/destroy`, `/vm/capabilities/refresh` to prevent runtime abuse, VM spam, and internal denial-of-service.

---

## 8. Dashboard — `app/vm_dashboard.py`

Single-file, follows existing dashboard pattern.

| Panel | Source | Refresh |
|-------|--------|---------|
| VM Topology | `/vm/list` + lineage graph | 5s |
| Capability Map | `/vm/capabilities` — tier availability, OS, docker runtime | 30s |
| Negotiation Feed | `/vm/negotiation/history` — requested vs actual, fallback reasons | 10s |
| microVM Activity | Firecracker/QEMU sessions — boot times, CPU/RAM | 5s |
| Escape Attempts | `/vm/threats` — signal type, severity, response | 5s |
| Disposable Pool | `/vm/pool/status` — warm/cold/unhealthy per profile | 10s |
| Runtime Metrics | `vm_runtime_metrics` — entropy, crypto score, burst alerts, hypervisor pressure | 5s |
| Forensic Timelines | `/vm/forensics/{id}` — expandable per-VM | on demand |
| Quarantine VMs | `/vm/list?status=QUARANTINED` | 5s |
| Emergency Events | `vm_events` CRITICAL rows — hash chain indicator | 3s |
| **Threat Overlays** | Attack propagation chains, runtime correlation graph, quarantine cascades | 10s |
| **Isolation Degradation Map** | Per-tier degradation events, fallback chains visualized | 10s |
| **Risk Heatmap** | risk_adjusted_score per active VM, color-coded | 5s |
| **Isolation Confidence Score** | Computed: runtime health + tier + anomaly load + hypervisor pressure + escape attempts + policy violations | 5s |

**Isolation Confidence Score** formula:
```
base = security_score (tier-based)
- anomaly_penalty (active anomaly count × 3)
- escape_penalty (escape attempts × 15)
- policy_violation_penalty (violations × 5)
- hypervisor_pressure_penalty (hypervisor_pressure_score × 10)
+ health_bonus (isolation_stability_score × 5)
= confidence_score (clamped 0–100)
```

---

## 9. Integration Map

No existing file is modified. All integration is additive.

```python
# Drivers wrap existing singletons (no modifications to wrapped code):
get_sandbox_manager()     → SandboxDriver
get_isolation_manager()   → ProcessJailDriver
get_container_manager()   → DockerHardenedDriver

# Emergency pipeline writes to (cross-layer alerts only):
get_restore_manager()          → step 7: rollback readiness
get_policy_engine()            → step 6: policy breach
get_permission_manager()       → step 6: agent flag
get_ast_engine()               → step 6: agent_id flag

# BehavioralLab → vm_network_isolation:
get_behavioral_lab().get_fake_internet_router()
→ vm_network_isolation.attach_fake_internet(bridge, router)

# BehavioralLab → risk scoring:
get_behavioral_lab().on_honeytoken_theft(vm_id)
→ increases risk_adjusted_score in NegotiationResult

# Future hooks (stubs now, activated later):
get_hardening_layer().escalate_host_protection(vm_id)   # pipeline step 8
get_hardening_layer().trigger_seccomp_escalation(vm_id) # pipeline step 8
```

### Singleton getters (consistent with project pattern)

```python
# core/vm_isolation/__init__.py
def get_vm_manager() -> VMManager: ...

# core/isolation_abstraction/__init__.py
def get_unified_runtime() -> UnifiedIsolationRuntime: ...
def get_capability_detector() -> IsolationCapabilityDetector: ...
def get_negotiator() -> IsolationNegotiator: ...
```

---

## 10. Future-Readiness Hooks

These are explicitly designed-in extension points, not afterthoughts:

| Feature | Hook Location | Status |
|---------|--------------|--------|
| Remote Linux execution nodes | `node_id`, `cluster_id` in DB + `supports_remote_nodes` in capabilities | Schema ready, logic stub |
| GPU secure runtimes | `supports_gpu_isolation`, `supports_virtualized_gpu` in capabilities | Field ready |
| Distributed forensic nodes | `cross_runtime_correlations`, `campaign_correlation_id` | Schema ready |
| Measured boot / TPM attestation | `tpm_measurement`, `attestation_report` in `vm_snapshots` + `supports_attestation` | Field ready |
| Signed policy updates | `policy_signature` in `vm_policies` | Field ready |
| Remote Firecracker clusters | `supports_remote_execution` in capabilities | Field ready |
| The Architect integration | `UnifiedIsolationRuntime.execute_isolated(minimum_security_score=90, requires_forensics=True)` | API ready |
| Host hardening escalation | `host_protection_escalation()` stub in pipeline step 8 | Stub ready |

---

## 11. File Count Summary

| Folder | Files |
|--------|-------|
| `core/isolation_abstraction/` | 7 |
| `core/vm_isolation/` | 17 |
| `app/routes/vm_routes.py` | 1 |
| `app/vm_dashboard.py` | 1 |
| `data/nexus_vm_isolation.db` | 1 (SQLite) |
| **Total new files** | **27** |

---

## 12. Implementation Order

1. Core contracts (`isolation_driver.py`, `DriverCapabilities`, `RuntimeHandle`, `NegotiationResult`)
2. Capability detection (`isolation_capability_detector.py`)
3. Strategy + negotiation (`isolation_strategy_manager.py`, `isolation_negotiator.py`)
4. Drivers — Tiers 3–5 first (Docker, Sandbox, ProcessJail — testable on Windows now)
5. Unified runtime + audit logger (`unified_isolation_runtime.py`, `isolation_audit_logger.py`)
6. VM internals (policy engine, snapshot manager, network isolation, filesystem guard, resource limiter)
7. VM manager + microVM manager + Firecracker/QEMU runtimes
8. Escape detector + forensics + quarantine
9. Hypervisor guardian (daemon)
10. Disposable VM pool
11. DB schema (`nexus_vm_isolation.db`)
12. API routes + dashboard
13. Integration hooks (recovery, behavioral lab, AST engine)
14. Future stubs (host protection escalation, attestation, distributed nodes)
