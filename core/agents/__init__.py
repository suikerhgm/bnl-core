from core.agents.agent_registry import AgentRegistry, registry
from core.agents.planner_agent import PlannerAgent
from core.actions.code_action import CodeAction
from core.actions.backend_action import BackendAction
from core.agents.nexus_registry import NexusAgentRegistry, get_registry

# Wire up the class-based routing registry used by the orchestrator
registry.register("planner", PlannerAgent)
registry.register("frontend", CodeAction)
registry.register("backend", BackendAction)

__all__ = [
    "AgentRegistry", "registry",
    "NexusAgentRegistry", "get_registry",
    "PlannerAgent", "BackendAction",
]
