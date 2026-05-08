# core/isolation_abstraction/__init__.py
# Public API — imported by callers
# Full imports are in each submodule to avoid circular imports at package init time.
from .isolation_driver import (
    IsolationTier,
    IsolationDriver,
    DriverCapabilities,
    RuntimeHandle,
    RuntimeLifecycleState,
    ExecutionPayload,
    ExecutionContext,
    ExecutionResult,
    SnapshotRef,
    RuntimeConfig,
    RuntimeHealthStats,
    TIER_CAPABILITIES,
    TIER_SECURITY_SCORES,
    TIER_RISK_ADJUSTMENTS,
    _set_handle_state,
    _get_handle_state,
    _clear_handle_state,
)

__all__ = [
    "IsolationTier",
    "IsolationDriver",
    "DriverCapabilities",
    "RuntimeHandle",
    "RuntimeLifecycleState",
    "ExecutionPayload",
    "ExecutionContext",
    "ExecutionResult",
    "SnapshotRef",
    "RuntimeConfig",
    "RuntimeHealthStats",
    "TIER_CAPABILITIES",
    "TIER_SECURITY_SCORES",
    "TIER_RISK_ADJUSTMENTS",
    "_set_handle_state",
    "_get_handle_state",
    "_clear_handle_state",
]
