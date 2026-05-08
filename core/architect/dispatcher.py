# core/architect/dispatcher.py
"""
ArchitectDispatcher — routes PlanTasks to the correct specialized agent.
Tries the registry first; falls back to direct agent instantiation.
Logs each dispatch to the audit trail.
"""
from __future__ import annotations
import logging
from typing import Optional

from core.agents.specialized.backend_agent import BackendAgent
from core.agents.specialized.frontend_agent import FrontendAgent
from core.agents.specialized.testing_agent import TestingAgent
from core.agents.specialized.repair_agent import RepairAgent
from core.agents.specialized.security_agent import SecurityAgent
from core.agents.specialized._base import AgentResult

logger = logging.getLogger(__name__)

_AGENT_MAP = {
    "backend":  BackendAgent,
    "frontend": FrontendAgent,
    "testing":  TestingAgent,
    "repair":   RepairAgent,
    "security": SecurityAgent,
}


class ArchitectDispatcher:
    """Routes tasks to specialized agents. No registry dependency for FASE 1."""

    async def dispatch(self, task: dict) -> AgentResult:
        """Dispatch a single task to the appropriate specialized agent."""
        agent_type = task.get("agent_type") or task.get("type", "backend")
        agent_cls = _AGENT_MAP.get(agent_type)

        if agent_cls is None:
            logger.warning("No agent for type=%s, falling back to BackendAgent", agent_type)
            agent_cls = BackendAgent

        logger.info("Dispatching task_id=%s type=%s to %s",
                    task.get("id", "?"), agent_type, agent_cls.__name__)

        agent = agent_cls()
        result = await agent.execute(task)

        if result.success:
            logger.info("Task %s completed: %s files", task.get("id"), len(result.files_created))
        else:
            logger.warning("Task %s failed: %s", task.get("id"), result.error)

        return result

    async def dispatch_all(
        self,
        tasks: list[dict],
        stop_on_failure: bool = False,
    ) -> list[AgentResult]:
        """Dispatch all tasks sequentially, respecting depends_on order."""
        results: list[AgentResult] = []
        completed_ids: set[str] = set()
        failed_ids: set[str] = set()

        # Sort by priority
        sorted_tasks = sorted(tasks, key=lambda t: t.get("priority", 99))

        for task in sorted_tasks:
            task_id = task.get("id", "")
            depends_on = task.get("depends_on", [])

            # Skip if any dependency failed
            if any(dep in failed_ids for dep in depends_on):
                logger.warning("Skipping task %s — dependency failed", task_id)
                continue

            result = await self.dispatch(task)
            results.append(result)

            if result.success:
                completed_ids.add(task_id)
            else:
                failed_ids.add(task_id)
                if stop_on_failure:
                    break

        return results
