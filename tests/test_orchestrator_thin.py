import inspect
import importlib


def test_orchestrator_only_exports_process_message():
    """Orchestrator must be a thin controller with no logic besides process_message."""
    mod = importlib.import_module("orchestrators.conversation_orchestrator")
    public_names = [n for n in dir(mod) if not n.startswith("_")]
    allowed = {"process_message", "ExecutionEngine", "Dict"}
    unexpected = set(public_names) - allowed
    assert not unexpected, f"Unexpected public names in thin orchestrator: {unexpected}"


def test_orchestrator_process_message_is_coroutine():
    from orchestrators.conversation_orchestrator import process_message
    assert inspect.iscoroutinefunction(process_message)
