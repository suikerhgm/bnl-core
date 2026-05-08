# core/architect/planner.py
"""
ArchitectPlanner — generates a structured execution plan for a given goal.
Deterministic, no AI. Detects what phases are needed and returns ordered tasks.
Used by ArchitectCore.execute_goal() as the planning phase.
"""
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlanTask:
    id: str
    type: str                    # backend | frontend | testing | security | repair
    description: str
    priority: int                # 1 = first
    depends_on: list[str] = field(default_factory=list)
    agent_type: str = ""         # which specialized agent runs this


@dataclass
class ExecutionPlan:
    goal: str
    plan_id: str
    tasks: list[PlanTask]
    project_name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Keywords that signal each phase is needed
_FRONTEND_KEYS = ["frontend", "ui", "interface", "pantalla", "página", "html", "web app", "single page"]
_BACKEND_KEYS  = ["api", "backend", "endpoint", "server", "fastapi", "rest", "crud", "notas", "tareas",
                  "app", "aplicación", "todo", "notes", "tasks", "inventory", "products"]
_TESTING_KEYS  = ["test", "testing", "prueba", "verificar", "coverage"]
_SECURITY_KEYS = ["security", "seguridad", "scan", "vulnerable", "auth", "token"]


class ArchitectPlanner:
    """
    Generates an execution plan from a natural language goal.
    Always includes: security scan → backend → (frontend if web) → testing.
    """

    def plan(self, goal: str, project_path: str = "") -> ExecutionPlan:
        lower = goal.lower()
        plan_id = str(uuid.uuid4())
        project_name = self._derive_name(goal)

        needs_backend  = True  # always
        needs_frontend = any(kw in lower for kw in _FRONTEND_KEYS)
        needs_testing  = any(kw in lower for kw in _TESTING_KEYS)
        needs_security = True  # always scan

        tasks: list[PlanTask] = []

        # Task 1: Backend generation (always first)
        backend_id = str(uuid.uuid4())
        tasks.append(PlanTask(
            id=backend_id,
            type="backend",
            description=goal,
            priority=1,
            agent_type="backend",
        ))

        # Task 2: Security scan of generated backend
        sec_id = str(uuid.uuid4())
        tasks.append(PlanTask(
            id=sec_id,
            type="security",
            description=f"Security scan of {project_name} backend",
            priority=2,
            depends_on=[backend_id],
            agent_type="security",
        ))

        # Task 3: Frontend (if web app)
        if needs_frontend:
            fe_id = str(uuid.uuid4())
            tasks.append(PlanTask(
                id=fe_id,
                type="frontend",
                description=goal,
                priority=3,
                depends_on=[backend_id],
                agent_type="frontend",
            ))

        # Task 4: Testing (if requested or always for apps)
        if needs_testing:
            test_id = str(uuid.uuid4())
            dep = [backend_id] + ([fe_id] if needs_frontend else [])
            tasks.append(PlanTask(
                id=test_id,
                type="testing",
                description=f"Tests for {project_name}",
                priority=4,
                depends_on=dep,
                agent_type="testing",
            ))

        return ExecutionPlan(
            goal=goal,
            plan_id=plan_id,
            tasks=tasks,
            project_name=project_name,
        )

    @staticmethod
    def _derive_name(goal: str) -> str:
        clean = re.sub(r"[^a-z0-9\s]", "", goal.lower())
        words = clean.split()[:3]
        return "_".join(words) if words else "app"
