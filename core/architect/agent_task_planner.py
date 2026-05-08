# core/architect/agent_task_planner.py
"""
AgentTaskPlanner — FASE 1: keyword-based classification.
AI call structure is prepared but not activated. All routing is deterministic.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.architect.models import (
    AgentTask, TaskPlan, RetryPolicy,
    CAPABILITY_MAP, DEPARTMENT_MAP, RISK_TO_POLICY,
    RISK_TO_MIN_TRUST, RISK_TO_MIN_SECURITY_SCORE,
)

_TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "security_scan":   ["security", "vulnerability", "scan", "audit", "threat", "exploit"],
    "frontend_ui":     ["ui", "frontend", "component", "interface", "dashboard", "css", "html"],
    "api_design":      ["api", "endpoint", "rest", "graphql", "route", "swagger"],
    "data_pipeline":   ["pipeline", "etl", "dataset", "transform", "ingestion", "stream"],
    "deployment":      ["deploy", "release", "ci/cd", "kubernetes", "production", "staging"],
    "test_automation": ["test", "unittest", "pytest", "coverage", "mock", "fixture"],
    "threat_model":    ["threat model", "attack surface", "risk model", "stride"],
    "file_write":      ["write file", "save file", "create file", "update file"],
    "code_generate":   ["create", "build", "generate", "implement", "write", "develop", "make", "code"],
}

_HIGH_RISK_KEYWORDS = ["production", "deploy", "shutdown", "drop", "truncate", "root", "admin"]
_MEDIUM_RISK_KEYWORDS = ["delete", "remove", "update", "modify", "overwrite", "write", "config"]
_CRITICAL_PHRASES = ["production deploy", "root access", "shutdown system", "drop database"]


class AgentTaskPlanner:
    """
    Classifies user requests into TaskPlan via keyword matching (FASE 1).
    FASE 2: replace _classify() with AI call, keep _decompose() unchanged.
    """

    def plan(
        self,
        user_request: str,
        origin: str = "user",
        parent_request_id: Optional[str] = None,
    ) -> TaskPlan:
        classification = self._classify(user_request)
        subtasks = self._decompose(classification, user_request)
        return TaskPlan(
            plan_id=str(uuid.uuid4()),
            parent_request_id=parent_request_id,
            origin=origin,
            created_at=datetime.now(timezone.utc),
            original_request=user_request,
            task_type=classification["task_type"],
            complexity=classification["complexity"],
            risk_level=classification["risk_level"],
            ai_reasoning=classification["reasoning"],
            subtasks=subtasks,
            requires_human_approval=(classification["risk_level"] == "critical"),
            performance_snapshot={},
        )

    def _classify(self, request: str) -> dict:
        """Keyword-based classification. FASE 2: replace body with AI call."""
        lower = request.lower()

        def _matches(kw: str, text: str) -> bool:
            # Use word-boundary match for short keywords (≤3 chars) to avoid
            # substring false positives like "ui" in "build" or "function".
            if len(kw) <= 3:
                return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))
            return kw in text

        task_type = "code_generate"
        for tt, keywords in _TASK_TYPE_KEYWORDS.items():
            if any(_matches(kw, lower) for kw in keywords):
                task_type = tt
                break

        risk_level = "low"
        if any(phrase in lower for phrase in _CRITICAL_PHRASES):
            risk_level = "critical"
        elif any(kw in lower for kw in _HIGH_RISK_KEYWORDS):
            risk_level = "high"
        elif any(kw in lower for kw in _MEDIUM_RISK_KEYWORDS):
            risk_level = "medium"

        complexity = "simple" if len(request.split()) < 10 else "moderate"

        return {
            "task_type": task_type,
            "risk_level": risk_level,
            "complexity": complexity,
            "reasoning": f"keyword_match: task_type={task_type} risk={risk_level}",
        }

    def _decompose(self, classification: dict, request: str) -> list[AgentTask]:
        task_type = classification["task_type"]
        risk_level = classification["risk_level"]
        payload = {"description": request, "task_type": task_type}
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        return [AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            description=request,
            required_capabilities=CAPABILITY_MAP.get(task_type, []),
            required_department=DEPARTMENT_MAP.get(task_type, "engineering"),
            payload=payload,
            payload_hash=payload_hash,
            priority={"low": 2, "medium": 3, "high": 4, "critical": 5}.get(risk_level, 2),
            risk_level=risk_level,
            depends_on=[],
            minimum_trust_level=RISK_TO_MIN_TRUST[risk_level],
            isolation_policy=RISK_TO_POLICY[risk_level],
            timeout_seconds=30,
            retry_policy=RetryPolicy(max_retries=1 if risk_level == "low" else 0),
            expected_output_type="code" if task_type == "code_generate" else "report",
        )]
