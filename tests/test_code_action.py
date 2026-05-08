"""
Tests para CodeAction (sin llamar a AI real).
"""
import sys
import asyncio

from core.actions.code_action import (
    _extract_code,
    _build_generate_prompt,
    _build_refactor_prompt,
    _build_debug_prompt,
    _build_prompt,
    CodeAction,
)
from core.action_router import ActionRouter


def test_extract_code():
    # Sin bloques de codigo
    assert _extract_code("texto normal") == "texto normal"
    # Con bloque simple
    assert _extract_code("```\nprint(1)\n```") == "print(1)"
    # Con lenguaje
    assert _extract_code("```python\nx = 1\n```") == "x = 1"
    # Multi-linea
    result = _extract_code("```\ndef foo():\n    return 42\n```")
    assert result == "def foo():\n    return 42"
    print("  PASS _extract_code")


def test_prompt_builders():
    # generate
    p = _build_generate_prompt("crea un boton")
    assert "crea un boton" in p
    assert "Genera" in p

    # generate con codigo existente
    p2 = _build_generate_prompt("mejora", "x = 1")
    assert "x = 1" in p2
    print("  PASS _build_generate_prompt")

    # refactor
    p = _build_refactor_prompt("mejora", "x = 1")
    assert "x = 1" in p
    assert "Refactoriza" in p
    print("  PASS _build_refactor_prompt")

    # debug
    p = _build_debug_prompt("corrige", "x = 1/0")
    assert "x = 1/0" in p
    assert "Depura" in p
    print("  PASS _build_debug_prompt")


def test_build_prompt():
    msgs = _build_prompt("generate", "test request")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "test request" in msgs[1]["content"]

    msgs = _build_prompt("refactor", "test", "x = 1")
    assert len(msgs) == 2
    assert "x = 1" in msgs[1]["content"]

    msgs = _build_prompt("debug", "test")
    assert len(msgs) == 2
    print("  PASS _build_prompt")


def test_extract_user_request():
    # Desde params
    ca = CodeAction({
        "operation": "generate",
        "params": {"request": "haz un componente de login en react native"},
    })
    req = ca._extract_user_request()
    assert req == "haz un componente de login en react native", f"Got: {req}"
    print("  PASS _extract_user_request desde params")

    # Desde decision_trace
    ca2 = CodeAction({
        "operation": "generate",
        "params": {},
        "decision_trace": {"user_message": "crea un formulario"},
    })
    req2 = ca2._extract_user_request()
    assert req2 == "crea un formulario", f"Got: {req2}"
    print("  PASS _extract_user_request desde decision_trace")

    # Fallback desde context
    ca3 = CodeAction({
        "operation": "generate",
        "params": {},
        "decision_trace": {},
        "message": "fallback message",
    })
    req3 = ca3._extract_user_request()
    assert req3 == "fallback message", f"Got: {req3}"
    print("  PASS _extract_user_request fallback")

    # Sin request
    ca4 = CodeAction({"operation": "generate", "params": {}})
    req4 = ca4._extract_user_request()
    assert req4 is None, f"Expected None, got: {req4}"
    print("  PASS _extract_user_request retorna None")


def test_requires_approval():
    assert not CodeAction({"operation": "generate", "params": {}}).requires_approval()
    assert CodeAction({"operation": "refactor", "params": {}}).requires_approval()
    assert CodeAction({"operation": "debug", "params": {}}).requires_approval()
    assert not CodeAction({"operation": "lint", "params": {}}).requires_approval()
    print("  PASS requires_approval")


def test_get_description():
    ca = CodeAction({"operation": "generate", "params": {}})
    desc = ca.get_description()
    assert "generar" in desc.lower(), f"Got: {desc}"
    ca2 = CodeAction({"operation": "refactor", "params": {}})
    assert "refactor" in ca2.get_description().lower()
    ca3 = CodeAction({"operation": "debug", "params": {}})
    assert "debug" in ca3.get_description().lower()
    print("  PASS get_description")


def test_action_router_integration():
    """Test que ActionRouter puede crear CodeAction correctamente."""
    action = ActionRouter.route(
        {"user_message": "haz un componente login"},
        "code_generate",
        {"params": {"request": "haz un componente login en react"}},
    )
    assert action is not None, "ActionRouter.route returned None for code_generate"
    assert action.action_type == "CodeAction"
    assert action.operation == "generate"

    # Con code_refactor
    action2 = ActionRouter.route(
        {"user_message": "mejora este codigo"},
        "code_refactor",
        {"params": {"request": "mejora este codigo", "code": "x = 1"}},
    )
    assert action2 is not None
    assert action2.operation == "refactor"
    assert action2.requires_approval() == True

    print("  PASS ActionRouter integration")


def test_lint_format_unimplemented():
    """Test que lint y format retornan error gracefulmente."""
    async def _test():
        ca = CodeAction({"operation": "lint", "params": {}})
        result = await ca.execute()
        assert result["success"] == False
        assert "no implementado" in result["error"].lower()
        print("  PASS lint retorna error graceful")

        ca2 = CodeAction({"operation": "format", "params": {}})
        result2 = await ca2.execute()
        assert result2["success"] == False
        assert "no implementado" in result2["error"].lower()
        print("  PASS format retorna error graceful")

    asyncio.run(_test())


def test_execute_no_request():
    """Test que execute retorna error si no hay request."""
    async def _test():
        ca = CodeAction({"operation": "generate", "params": {}})
        result = await ca.execute()
        assert result["success"] == False
        assert "solicitud" in result["error"].lower()
        print("  PASS execute retorna error sin request")

    asyncio.run(_test())


if __name__ == "__main__":
    print("=" * 50)
    print("CodeAction Tests (sin AI)")
    print("=" * 50)

    test_extract_code()
    test_prompt_builders()
    test_build_prompt()
    test_extract_user_request()
    test_requires_approval()
    test_get_description()
    test_action_router_integration()
    test_lint_format_unimplemented()
    test_execute_no_request()

    print()
    print("=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
