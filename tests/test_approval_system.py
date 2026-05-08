"""
🧪 Test manual del Approval System con integración a Telegram.

Para probar el flujo completo:

1. Asegurarse de que nexus_bot.py esté corriendo:
   uvicorn nexus_bot:app --host 0.0.0.0 --port 8001

2. Obtener tu chat_id de Telegram desde los logs del servidor

3. Actualizar TELEGRAM_CHAT_ID abajo con tu chat_id real

4. Ejecutar: python test_approval_system.py

5. Recibirás el mensaje en Telegram con /aprobar <id> y /rechazar <id>

6. Responde con uno de esos comandos para ver el flujo completo
"""

import asyncio
import sys
import os

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.approval_system import ApprovalSystem
from core.actions.notion_action import NotionAction


async def test_approval_flow():
    """
    Test manual del flujo de aprobación.
    """
    print("=" * 60)
    print("🧪 Testing Approval System with Telegram")
    print("=" * 60)

    # ── Configuración ─────────────────────────────────────────
    # IMPORTANTE: Reemplaza con tu chat_id real de Telegram
    TELEGRAM_CHAT_ID = 123456789  # ← CAMBIAR ESTO
    # ──────────────────────────────────────────────────────────

    print(f"\n📋 Configuracion:")
    print(f"   Telegram Chat ID: {TELEGRAM_CHAT_ID}")

    # Crear acción que requiere aprobación (delete)
    context = {
        "operation": "delete",
        "params": {"page_id": "test-page-123"},
    }
    action = NotionAction(context)

    print(f"\n📋 Accion a aprobar:")
    print(f"   Type: {action.action_type}")
    print(f"   Requires approval: {action.requires_approval()}")
    print(f"   Description: {action.get_description()}")
    print(f"   Pending approvals: {ApprovalSystem.get_pending_count()}")

    print(f"\n📤 Enviando solicitud de aprobacion a Telegram...")
    print(f"   (Revisa tu Telegram, deberias recibir un mensaje)")
    print(f"   Timeout: 5 minutos\n")

    result = await ApprovalSystem.request_approval(action, TELEGRAM_CHAT_ID)

    print(f"\n{'=' * 60}")
    if result is True:
        print("✅ RESULTADO: Accion APROBADA")
    elif result is False:
        print("❌ RESULTADO: Accion RECHAZADA")
    elif result is None:
        print("⏰ RESULTADO: Timeout - No hubo respuesta en 5 min")
    print(f"{'=' * 60}")

    print(f"\n📊 Pending approvals restantes: {ApprovalSystem.get_pending_count()}")

    print(f"\n✅ Test completado")


async def test_approval_resolve():
    """
    Test unitario: Resolver aprobación sin Telegram.
    """
    print("\n" + "=" * 60)
    print("🧪 Testing ApprovalSystem.resolve_approval() (sin Telegram)")
    print("=" * 60)

    from core.actions.notion_action import NotionAction

    context = {
        "operation": "delete",
        "params": {"page_id": "unit-test-page"},
    }
    action = NotionAction(context)

    # Simular una aprobación sin enviar a Telegram (modo directo)
    import uuid
    approval_id = str(uuid.uuid4())[:8]

    # Verificar que el ID no existe
    assert ApprovalSystem.resolve_approval(approval_id, True) is False, \
        "Deberia fallar porque no hay pending approval con ese ID"

    print("✅ OK: Resolver ID inexistente retorna False")

    # Ahora creamos una aprobación manualmente inyectando un future
    import asyncio
    from core.approval_system import _pending_approvals

    future = asyncio.Future()
    _pending_approvals[approval_id] = future

    # Verificar pending count
    assert ApprovalSystem.get_pending_count() >= 1
    print(f"✅ OK: Pending count = {ApprovalSystem.get_pending_count()}")

    # Resolver como aprobada
    success = ApprovalSystem.resolve_approval(approval_id, True)
    assert success is True, "Deberia resolver correctamente"
    assert future.result() is True, "Future deberia ser True"

    print("✅ OK: resolve_approval(True) funciona")

    # Verificar que doble resolución falla
    success2 = ApprovalSystem.resolve_approval(approval_id, True)
    assert success2 is False, "Doble resolucion deberia fallar"

    print("✅ OK: Doble resolucion retorna False")

    # Test con rechazo
    approval_id2 = str(uuid.uuid4())[:8]
    future2 = asyncio.Future()
    _pending_approvals[approval_id2] = future2
    ApprovalSystem.resolve_approval(approval_id2, False)
    assert future2.result() is False, "Future deberia ser False"

    print("✅ OK: resolve_approval(False) funciona")

    print(f"\n✅ Todos los tests unitarios pasados")


async def main():
    print("🧪 Approval System Test Suite")
    print("=" * 60)

    # Test unitario (siempre funciona, no requiere Telegram)
    await test_approval_resolve()

    print("\n")
    # Test con Telegram (requiere chat_id real)
    await test_approval_flow()


if __name__ == "__main__":
    asyncio.run(main())
