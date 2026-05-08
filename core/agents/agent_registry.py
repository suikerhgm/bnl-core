class AgentRegistry:

    def __init__(self):
        self._agents = {}

    def register(self, name: str, agent_cls):
        self._agents[name] = agent_cls

    def get(self, name: str):
        return self._agents.get(name)

    def list_agents(self):
        return list(self._agents.keys())


# Module-level singleton — import this in consumers
registry = AgentRegistry()
