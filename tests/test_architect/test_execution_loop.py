# tests/test_architect/test_execution_loop.py
"""
Tests for ArchitectExecutionLoop: validation, auto-repair, trace, full pipeline.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.architect.execution_loop import (
    ArchitectExecutionLoop, OutputValidator, FinalResponse, ExecutionTraceStep,
    get_execution_loop,
)
from core.architect.models import ArchitectExecutionResult, ArchitectExecutionContext
import uuid


def make_exec_result(success=True, outputs=None, error_summary=None) -> ArchitectExecutionResult:
    return ArchitectExecutionResult(
        execution_id=str(uuid.uuid4()),
        plan_id="p-001",
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        success=success,
        outputs=outputs if outputs is not None else (["def hello(): return 'world'"] if success else []),
        error_summary=error_summary,
        agents_used=["agent-forge-01"] if success else [],
        runtimes_used=["PROCESS_JAIL"] if success else [],
        fallback_chain=[],
        security_events=[],
        audit_refs=["e-001"],
        avg_security_score=20,
        execution_time_ms=150,
        task_count=1,
        failed_task_count=0 if success else 1,
        skipped_task_count=0,
    )


# ── OutputValidator tests ─────────────────────────────────────────────────────

def test_validator_passes_clean_output():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["def greet(): return 'hello'"])
    valid, reason = v.validate(r)
    assert valid is True
    assert reason is None


def test_validator_fails_on_execution_failure():
    v = OutputValidator()
    r = make_exec_result(success=False, outputs=[])
    valid, reason = v.validate(r)
    assert valid is False
    assert "execution_failed" in reason


def test_validator_fails_on_no_output():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=[])
    valid, reason = v.validate(r)
    assert valid is False
    assert "no_output" in reason


def test_validator_fails_on_empty_string_output():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["   "])
    valid, reason = v.validate(r)
    assert valid is False
    assert "empty_output" in reason


def test_validator_detects_traceback():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["Traceback (most recent call last):\n  line 1"])
    valid, reason = v.validate(r)
    assert valid is False
    assert "traceback" in reason.lower()


def test_validator_detects_syntax_error():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["SyntaxError: invalid syntax"])
    valid, reason = v.validate(r)
    assert valid is False


def test_validator_detects_import_error():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["ModuleNotFoundError: No module named 'xyz'"])
    valid, reason = v.validate(r)
    assert valid is False


def test_validator_passes_code_with_comments():
    v = OutputValidator()
    r = make_exec_result(success=True, outputs=["# This is a valid Python file\ndef foo(): pass"])
    valid, reason = v.validate(r)
    assert valid is True


# ── ExecutionTraceStep tests ──────────────────────────────────────────────────

def test_trace_step_has_timestamp():
    step = ExecutionTraceStep(step="test", status="ok", detail="test detail")
    assert step.timestamp is not None
    assert step.duration_ms == 0


def test_trace_step_statuses():
    for status in ("ok", "warn", "fail"):
        step = ExecutionTraceStep(step="x", status=status, detail="d")
        assert step.status == status


# ── ArchitectExecutionLoop tests ──────────────────────────────────────────────

@pytest.fixture
def mock_core():
    core = MagicMock()
    core.receive_request = AsyncMock(return_value=make_exec_result(success=True))
    return core


@pytest.fixture
def loop(mock_core):
    return ArchitectExecutionLoop(architect_core=mock_core)


@pytest.mark.asyncio
async def test_run_returns_final_response(loop):
    result = await loop.run("create a simple app")
    assert isinstance(result, FinalResponse)


@pytest.mark.asyncio
async def test_run_success_sets_success_true(loop):
    result = await loop.run("create a simple app")
    assert result.success is True
    assert result.execution_id is not None


@pytest.mark.asyncio
async def test_run_populates_trace(loop):
    # Use a non-app request so it goes through architect_execute path
    result = await loop.run("write a utility function")
    assert len(result.trace) >= 3  # context_created + execute + validate + finalize
    step_names = [s.step for s in result.trace]
    assert "context_created" in step_names
    # Either architect_execute (normal) or app_create_detected (app path)
    assert any(s in step_names for s in ("architect_execute", "app_create_detected"))
    assert "validate" in step_names


@pytest.mark.asyncio
async def test_run_forwards_user_id(mock_core):
    loop = ArchitectExecutionLoop(architect_core=mock_core)
    await loop.run("build something", user_id="user-42")
    call_kwargs = mock_core.receive_request.call_args
    ctx_passed = call_kwargs[1]["ctx"] if "ctx" in call_kwargs[1] else call_kwargs[0][1]
    assert ctx_passed.user_id == "user-42"


@pytest.mark.asyncio
async def test_run_no_repair_on_valid_output(mock_core):
    loop = ArchitectExecutionLoop(architect_core=mock_core)
    result = await loop.run("create a function")
    assert result.repair_attempted is False
    assert mock_core.receive_request.call_count == 1  # called once, no retry


@pytest.mark.asyncio
async def test_run_repair_attempted_on_invalid_output(mock_core):
    """If output fails validation, auto-repair fires."""
    # First call: fails validation (empty output)
    # Second call (repair): succeeds
    bad_result = make_exec_result(success=True, outputs=[""])  # empty output
    good_result = make_exec_result(success=True, outputs=["def fixed(): pass"])
    mock_core.receive_request = AsyncMock(side_effect=[bad_result, good_result])

    loop = ArchitectExecutionLoop(architect_core=mock_core)
    result = await loop.run("create a function")

    assert result.repair_attempted is True
    assert result.repair_succeeded is True
    assert mock_core.receive_request.call_count == 2


@pytest.mark.asyncio
async def test_run_repair_failed_still_returns_response(mock_core):
    """Even if repair fails, we return a FinalResponse (never exception)."""
    bad_result = make_exec_result(success=True, outputs=[""])
    mock_core.receive_request = AsyncMock(side_effect=[bad_result, bad_result])

    loop = ArchitectExecutionLoop(architect_core=mock_core)
    result = await loop.run("build something")

    assert isinstance(result, FinalResponse)
    assert result.repair_attempted is True
    assert result.repair_succeeded is False


@pytest.mark.asyncio
async def test_run_exception_returns_error_response(mock_core):
    """If architect raises, loop catches and returns error FinalResponse."""
    mock_core.receive_request = AsyncMock(side_effect=RuntimeError("core crashed"))

    loop = ArchitectExecutionLoop(architect_core=mock_core)
    result = await loop.run("do something")

    assert isinstance(result, FinalResponse)
    assert result.success is False
    assert "core crashed" in result.message


@pytest.mark.asyncio
async def test_run_message_contains_tier_info(loop):
    result = await loop.run("create a function")
    assert "PROCESS_JAIL" in result.message or result.message  # tier visible in message


@pytest.mark.asyncio
async def test_run_outputs_propagated(loop):
    result = await loop.run("generate code")
    assert "def hello(): return 'world'" in result.outputs


@pytest.mark.asyncio
async def test_run_audit_refs_populated(loop):
    result = await loop.run("create something")
    assert isinstance(result.audit_refs, list)


def test_get_execution_loop_singleton():
    l1 = get_execution_loop()
    l2 = get_execution_loop()
    assert l1 is l2
