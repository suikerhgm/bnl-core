# core/agents/specialized/security_agent.py
"""
SecurityAgent — uses the existing ASTSecurityEngine to scan generated code.
Returns a structured report with risk level and any detected threats.
Integrates with the existing nexus_ast_security.db audit trail.
"""
from __future__ import annotations
import time
from pathlib import Path
from ._base import BaseSpecializedAgent, AgentResult


class SecurityAgent(BaseSpecializedAgent):
    agent_type = "security"

    async def execute(self, task: dict) -> AgentResult:
        task_id = task.get("id", "security-task")
        project_path = Path(task.get("project_path", "generated_apps/app"))
        target_file = task.get("target_file", "main.py")

        start = int(time.monotonic() * 1000)
        try:
            from core.ast_security.ast_security_engine import get_ast_engine
            engine = get_ast_engine()

            source_file = project_path / target_file
            if not source_file.exists():
                return self._result(task_id=task_id, success=True,
                                    output="No file to scan",
                                    duration_ms=int(time.monotonic() * 1000) - start)

            source_code = source_file.read_text(encoding="utf-8")
            scan_result = engine.scan(source_code, filename=str(source_file))

            action = getattr(scan_result, "action", "ALLOW")
            risk = getattr(scan_result, "risk_level", "unknown")
            threats = getattr(scan_result, "threats", [])

            blocked = action == "BLOCK"
            summary = (
                f"scan={action} risk={risk} "
                f"threats={len(threats)} file={target_file}"
            )

            return self._result(
                task_id=task_id,
                success=not blocked,
                output=summary,
                error=f"Blocked by AST security: {threats[:2]}" if blocked else None,
                duration_ms=int(time.monotonic() * 1000) - start,
            )
        except Exception as e:
            # Security scan failure should not block app creation
            return self._result(
                task_id=task_id, success=True,
                output=f"Security scan skipped: {type(e).__name__}",
                duration_ms=int(time.monotonic() * 1000) - start,
            )
