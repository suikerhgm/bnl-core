import pytest
import importlib


def test_execution_engine_importable():
    mod = importlib.import_module("core.execution_engine")
    assert hasattr(mod, "ExecutionEngine")


def test_execution_engine_has_run():
    from core.execution_engine import ExecutionEngine
    engine = ExecutionEngine()
    assert hasattr(engine, "run")
    import inspect
    assert inspect.iscoroutinefunction(engine.run)
