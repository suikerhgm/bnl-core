"""
Test del pipeline completo: intent_detection -> ActionRouter -> CodeAction
"""
import asyncio

from core.memory_decision import MemoryDecisionLayer
from core.action_router import ActionRouter
from core.actions.code_action import CodeAction


def test_pipeline():
    """Test que un mensaje de usuario fluye por todo el pipeline."""
    test_cases = [
        {
            "message": "haz un componente de login en react native",
            "expected_intent": "code_generate",
            "expected_operation": "generate",
        },
        {
            "message": "refactoriza este codigo",
            "expected_intent": "code_refactor",
            "expected_operation": "refactor",
        },
        {
            "message": "debug this code",
            "expected_intent": "code_debug",
            "expected_operation": "debug",
        },
        {
            "message": "crea un archivo main.py",
            "expected_intent": "file_write",
            "expected_operation": "write",
        },
        {
            "message": "actualiza la pagina de notion",
            "expected_intent": "notion_update",
            "expected_operation": "update",
        },
    ]

    all_passed = 0
    for tc in test_cases:
        msg = tc["message"]
        exp_intent = tc["expected_intent"]
        exp_op = tc["expected_operation"]

        # 1. Detectar intent
        detected_intent = MemoryDecisionLayer._detect_intent(msg)
        assert detected_intent == exp_intent, (
            f"Intent mismatch for '{msg}': "
            f"expected '{exp_intent}', got '{detected_intent}'"
        )

        # 2. Routeo
        context = {
            "params": {"request": msg},
            "user_id": "test_user",
        }
        action = ActionRouter.route({}, detected_intent, context)
        assert action is not None, (
            f"ActionRouter.route returned None for intent '{detected_intent}'"
        )

        # 3. Verificar tipo y operacion
        assert action.operation == exp_op, (
            f"Operation mismatch: expected '{exp_op}', got '{action.operation}'"
        )

        # 4. Verificar que es CodeAction o accion valida
        if detected_intent.startswith("code_"):
            assert isinstance(action, CodeAction)
            assert action._extract_user_request() == msg

        all_passed += 1
        print(f"  PASS [{detected_intent}] '{msg[:40]}...' -> {action.action_type}.{action.operation}")

    print(f"\n  Todos los {all_passed} escenarios del pipeline pasaron")
    return True


if __name__ == "__main__":
    print("=" * 50)
    print("Pipeline completo: intent -> route -> action")
    print("=" * 50)
    test_pipeline()
    print("=" * 50)
    print("PIPELINE VERIFICADO")
    print("=" * 50)
