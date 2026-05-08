# core/architect/external_agent_integration.py (minimal stub for Task 1)
class ExternalAgentIntegration:
    async def onboard_external_agent(self, agent_spec: dict, requested_department: str):
        raise NotImplementedError("ExternalAgentIntegration — implement in FASE 3")
    async def promote_from_quarantine(self, agent_id: str, approved_by: str, new_trust_level: int) -> bool:
        raise NotImplementedError("promote_from_quarantine — implement in FASE 3")
