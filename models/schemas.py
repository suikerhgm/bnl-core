"""
NexusAgentes — Modelos Pydantic compartidos (schemas)
"""
from typing import Dict, List, Any, Optional

from pydantic import BaseModel


# ── Búsqueda ─────────────────────────────────
class SearchRequest(BaseModel):
    query: str


# ── Fetch ────────────────────────────────────
class FetchRequest(BaseModel):
    page_id: str


# ── Create ──────────────────────────────────
class CreateRequest(BaseModel):
    parent_id: str
    title: str
    content: str


# ── Build App (Nexus BNL) ───────────────────
class BuildAppRequest(BaseModel):
    project_name: Optional[str] = None
    idea: Optional[str] = None


class BuildAppResponse(BaseModel):
    project_name: str
    blueprint: Dict[str, Any]
    task_list: List[Dict[str, Any]]
    executed_task: Dict[str, Any]
    status: str


class PlanResponse(BaseModel):
    plan_id: str
    status: str
    blueprint: Dict[str, Any]
    tasks: List[Dict[str, Any]]


# ── Execute Plan ────────────────────────────
class ExecutePlanRequest(BaseModel):
    plan_id: str


class ExecutePlanResponse(BaseModel):
    plan_id: str
    status: str
    results: List[Dict[str, Any]]
