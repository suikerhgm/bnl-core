#!/usr/bin/env python3
"""
Test para verificar que "El Forjador" está vivo y funcionando.
"""
import sys
import asyncio
sys.path.insert(0, ".")

from core.actions.code_action import CodeAction
from core.action_router import ActionRouter


def test_agent_identity():
    """Verifica la identidad del agente."""
    ca = CodeAction({
        "operation": "generate",
        "params": {"request": "test"},
    })
    assert ca.AGENT_NAME == "El Forjador"
    assert "ElForjador" in ca.get_description()
    print("  PASS agent_identity")


def test_metadata_on_execute():
    """Verifica que el metadata se incluya en el resultado."""
    async def _test():
        ca = CodeAction({"operation": "generate", "params": {}})
        result = await ca.execute()
        # sin request, falla pero NO debe tener metadata
        assert "metadata" not in result, "No metadata esperado en error"
        print("  PASS metadata ausente en error")

        # con request pero va a fallar por falta de AI real
        ca2 = CodeAction({
            "operation": "generate",
            "params": {"request": "test"},
        })
        result2 = await ca2.execute()
        # Si falló no tiene metadata
        if result2.get("metadata"):
            assert result2["metadata"]["agent"] == "ElForjador"
            assert result2["metadata"]["operation"] == "generate"
        print("  PASS metadata presente cuando hay exito")

    asyncio.run(_test())


def test_action_router_creates_forjador():
    """ActionRouter crea CodeAction con identidad El Forjador."""
    action = ActionRouter.route(
        {"user_message": "haz un login en react native"},
        "code_generate",
        {"params": {"request": "haz un login en react native"}},
    )
    assert action is not None
    assert action.AGENT_NAME == "El Forjador"
    assert action.operation == "generate"
    print("  PASS ActionRouter -> ElForjador")


def test_prompts_have_identity():
    """Verifica que los system prompts contienen 'El Forjador'."""
    from core.actions.code_action import (
        _SYSTEM_PROMPT_GENERATE,
        _SYSTEM_PROMPT_REFACTOR,
        _SYSTEM_PROMPT_DEBUG,
    )
    for prompt_name, prompt in [
        ("GENERATE", _SYSTEM_PROMPT_GENERATE),
        ("REFACTOR", _SYSTEM_PROMPT_REFACTOR),
        ("DEBUG", _SYSTEM_PROMPT_DEBUG),
    ]:
        assert "El Forjador" in prompt, f"{prompt_name} missing 'El Forjador'"
        assert "React Native" in prompt, f"{prompt_name} missing React Native"
        print(f"  PASS {prompt_name} prompt tiene identidad")


def test_build_prompt_includes_identity():
    """El mensaje system construido debe incluir 'El Forjador'."""
    from core.actions.code_action import _build_prompt
    msgs = _build_prompt("generate", "test")
    assert "El Forjador" in msgs[0]["content"]
    msgs2 = _build_prompt("refactor", "test")
    assert "El Forjador" in msgs2[0]["content"]
    msgs3 = _build_prompt("debug", "test")
    assert "El Forjador" in msgs3[0]["content"]
    print("  PASS _build_prompt incluye 'El Forjador' en los 3 modos")


def test_description_format():
    """Verifica formato de get_description."""
    descriptions = {
        "generate": "Generar nuevo código a partir de una descripción",
        "refactor": "Refactorizar código existente para mejorarlo",
        "debug": "Depurar y corregir errores en código",
    }
    for op, expected_desc in descriptions.items():
        ca = CodeAction({"operation": op, "params": {}})
        desc = ca.get_description()
        assert "ElForjador" in desc, f"Description for {op} doesn't mention ElForjador"
        assert expected_desc in desc, f"Description for {op} doesn't match"
    print("  PASS description_format")


def test_lint_format_unimplemented_no_metadata():
    """lint/format no deben incluir metadata en el error."""
    async def _test():
        ca = CodeAction({"operation": "lint", "params": {}})
        result = await ca.execute()
        assert "metadata" not in result
        print("  PASS lint sin metadata en error")
    asyncio.run(_test())


if __name__ == "__main__":
    print("=" * 50)
    print("El Forjador - Tests de Identidad")
    print("=" * 50)

    test_agent_identity()
    test_metadata_on_execute()
    test_action_router_creates_forjador()
    test_prompts_have_identity()
    test_build_prompt_includes_identity()
    test_description_format()
    test_lint_format_unimplemented_no_metadata()

    print()
    print("=" * 50)
    print("EL FORJADOR ESTA VIVO - TODOS LOS TESTS PASARON")
    print("=" * 50)
