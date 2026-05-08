# core/architect/execution_loop.py
"""
ArchitectExecutionLoop — closes the pipeline from user request to final result.
Wraps ArchitectCore.receive_request() with:
  - basic output validation
  - single auto-repair attempt on failure (retry with SAFE_DEGRADATION)
  - visible execution trace
  - consolidated final response

The Architect IS the director: it speaks to the user and orchestrates Nexus.
Nexus = complete system. The Architect = operational director.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Output validator ──────────────────────────────────────────────────────────

class OutputValidator:
    """
    Validates that a task result meets basic quality criteria.
    FASE 1: simple heuristics. FASE 4: AI-based semantic validation.
    """

    def validate(self, result) -> tuple[bool, str | None]:
        """
        Returns (is_valid, failure_reason).
        failure_reason is None if valid.
        """
        if not result.success:
            return False, f"execution_failed: failed_tasks={result.failed_task_count}"

        if not result.outputs:
            return False, "no_output_produced"

        combined = " ".join(result.outputs)
        if not combined.strip():
            return False, "empty_output"

        # Check for common error markers in output
        lower = combined.lower()
        error_markers = [
            "traceback (most recent call last)",
            "syntaxerror:",
            "nameerror:",
            "importerror:",
            "modulenotfounderror:",
            "cannot import",
        ]
        for marker in error_markers:
            if marker in lower:
                return False, f"output_contains_error: {marker}"

        return True, None


# ── Execution trace ───────────────────────────────────────────────────────────

@dataclass
class ExecutionTraceStep:
    step: str
    status: str      # "ok" | "warn" | "fail"
    detail: str
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FinalResponse:
    """The consolidated response returned to the user."""
    success: bool
    message: str                              # human-readable result
    execution_id: str
    plan_id: str
    task_count: int
    agents_used: list[str]
    runtimes_used: list[str]
    avg_security_score: int
    execution_time_ms: int
    repair_attempted: bool
    repair_succeeded: bool
    trace: list[ExecutionTraceStep]
    outputs: list[str]
    error_summary: Optional[str] = None
    fallback_chain: list[dict] = field(default_factory=list)
    audit_refs: list[str] = field(default_factory=list)


# ── Main loop ─────────────────────────────────────────────────────────────────

class ArchitectExecutionLoop:
    """
    Closed-loop execution: request → plan → dispatch → validate → [repair] → response.
    The Architect is the operational director of Nexus.
    """

    def __init__(self, architect_core=None, validator=None) -> None:
        if architect_core is None:
            from core.architect.architect_core import get_architect_core
            architect_core = get_architect_core()
        self._core = architect_core
        self._validator = validator or OutputValidator()

    async def run(
        self,
        user_request: str,
        user_id: str = "user",
        trust_level: int = 50,
    ) -> FinalResponse:
        """
        Full pipeline: request → Architect → plan → dispatch → validate → [repair] → result.
        """
        from core.architect.models import ArchitectExecutionContext

        loop_start = int(time.monotonic() * 1000)
        trace: list[ExecutionTraceStep] = []

        # ── Step 1: Build context ─────────────────────────────────────────────
        ctx = ArchitectExecutionContext(
            user_id=user_id,
            trust_level=trust_level,
        )
        trace.append(ExecutionTraceStep(
            step="context_created",
            status="ok",
            detail=f"execution_id={ctx.execution_id[:8]}… user={user_id}",
        ))

        # ── Step 2: Execute through Architect ────────────────────────────────
        t0 = int(time.monotonic() * 1000)
        try:
            result = await self._core.receive_request(user_request, ctx=ctx)
        except Exception as e:
            trace.append(ExecutionTraceStep(
                step="architect_execute", status="fail",
                detail=f"exception: {type(e).__name__}: {e}",
            ))
            return self._build_error_response(ctx, str(e), trace, loop_start)

        exec_ms = int(time.monotonic() * 1000) - t0
        trace.append(ExecutionTraceStep(
            step="architect_execute",
            status="ok" if result.success else "fail",
            detail=(
                f"plan_id={result.plan_id[:8]}… "
                f"tasks={result.task_count} "
                f"agents={result.agents_used} "
                f"tiers={result.runtimes_used}"
            ),
            duration_ms=exec_ms,
        ))

        # ── Step 3: Validate output ───────────────────────────────────────────
        is_valid, failure_reason = self._validator.validate(result)
        trace.append(ExecutionTraceStep(
            step="validate",
            status="ok" if is_valid else "warn",
            detail=failure_reason or "output_valid",
        ))

        # ── Step 4: Auto-repair if needed ────────────────────────────────────
        repair_attempted = False
        repair_succeeded = False

        if not is_valid and result.task_count > 0:
            repair_attempted = True
            trace.append(ExecutionTraceStep(
                step="repair_attempt",
                status="warn",
                detail=f"reason={failure_reason} retrying with SAFE_DEGRADATION",
            ))

            repair_ctx = ArchitectExecutionContext(
                user_id=user_id,
                trust_level=trust_level,
                parent_execution_id=ctx.execution_id,
                correlation_id=ctx.correlation_id,   # same correlation chain
            )
            from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
            repair_ctx.isolation_policy = IsolationPolicy.SAFE_DEGRADATION

            try:
                repair_result = await self._core.receive_request(user_request, ctx=repair_ctx)
                repair_valid, _ = self._validator.validate(repair_result)
                if repair_valid:
                    result = repair_result
                    is_valid = True
                    repair_succeeded = True
                    trace.append(ExecutionTraceStep(
                        step="repair_result", status="ok", detail="repair_succeeded",
                    ))
                else:
                    trace.append(ExecutionTraceStep(
                        step="repair_result", status="fail", detail="repair_also_failed",
                    ))
            except Exception as e:
                trace.append(ExecutionTraceStep(
                    step="repair_result", status="fail",
                    detail=f"repair_exception: {type(e).__name__}",
                ))

        # ── Step 5: Build final response ──────────────────────────────────────
        total_ms = int(time.monotonic() * 1000) - loop_start
        trace.append(ExecutionTraceStep(
            step="finalize",
            status="ok" if (result.success and is_valid) else "warn",
            detail=f"total_ms={total_ms} repair={repair_attempted}",
        ))

        return self._build_response(result, ctx, trace, total_ms, repair_attempted, repair_succeeded)

    def _build_response(
        self, result, ctx, trace, total_ms, repair_attempted, repair_succeeded
    ) -> FinalResponse:
        success = result.success and bool(result.outputs)
        msg = self._format_message(result, repair_attempted, repair_succeeded)

        return FinalResponse(
            success=success,
            message=msg,
            execution_id=result.execution_id,
            plan_id=result.plan_id,
            task_count=result.task_count,
            agents_used=result.agents_used,
            runtimes_used=result.runtimes_used,
            avg_security_score=result.avg_security_score,
            execution_time_ms=total_ms,
            repair_attempted=repair_attempted,
            repair_succeeded=repair_succeeded,
            trace=trace,
            outputs=result.outputs,
            error_summary=result.error_summary,
            fallback_chain=result.fallback_chain,
            audit_refs=result.audit_refs,
        )

    def _build_error_response(self, ctx, error_msg, trace, loop_start) -> FinalResponse:
        total_ms = int(time.monotonic() * 1000) - loop_start
        return FinalResponse(
            success=False,
            message=f"The Architect encountered an error: {error_msg}",
            execution_id=ctx.execution_id,
            plan_id="",
            task_count=0,
            agents_used=[],
            runtimes_used=[],
            avg_security_score=0,
            execution_time_ms=total_ms,
            repair_attempted=False,
            repair_succeeded=False,
            trace=trace,
            outputs=[],
            error_summary=error_msg,
        )

    @staticmethod
    def _format_message(result, repair_attempted: bool, repair_succeeded: bool) -> str:
        parts = []
        if result.success:
            parts.append("Completed")
        else:
            parts.append("Failed")

        if result.runtimes_used:
            parts.append(f"[{', '.join(result.runtimes_used)}]")

        if result.agents_used:
            parts.append(f"via {len(result.agents_used)} agent(s)")

        if result.avg_security_score:
            parts.append(f"security={result.avg_security_score}")

        if repair_attempted:
            status = "repaired" if repair_succeeded else "repair failed"
            parts.append(f"({status})")

        if result.error_summary:
            parts.append(f"— {result.error_summary}")

        return " ".join(parts)


# ── Singleton ─────────────────────────────────────────────────────────────────

_loop_instance: Optional[ArchitectExecutionLoop] = None

def get_execution_loop() -> ArchitectExecutionLoop:
    global _loop_instance
    if _loop_instance is None:
        _loop_instance = ArchitectExecutionLoop()
    return _loop_instance
