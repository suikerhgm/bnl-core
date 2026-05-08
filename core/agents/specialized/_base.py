# core/agents/specialized/_base.py
"""
Base class for all specialized agents.
Each agent receives a task dict, executes its responsibility,
and returns a structured AgentResult.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AgentResult:
    agent_type: str
    task_id: str
    success: bool
    output: str
    files_created: list[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseSpecializedAgent:
    agent_type: str = "base"

    async def execute(self, task: dict) -> AgentResult:
        raise NotImplementedError

    def _result(self, task_id: str, success: bool, output: str,
                 files: list[str] = None, error: str = None,
                 duration_ms: int = 0) -> AgentResult:
        return AgentResult(
            agent_type=self.agent_type,
            task_id=task_id,
            success=success,
            output=output,
            files_created=files or [],
            error=error,
            duration_ms=duration_ms,
        )
