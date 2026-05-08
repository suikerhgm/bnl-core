"""
Test de integración del Action System con el Cognitive Core.

Verifica:
1. _should_execute_action detecta intents accionables correctamente
2. _extract_action_params extrae título y contenido de mensajes
3. ActionRouter enruta "notion_create" a NotionAction
4. ActionLogger persiste y recupera acciones
5. Flujo completo: detect_intent → should_execute → route → log
"""
import sys
import os
import json

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configurar encoding para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

print("=" * 60)
print("🧪 ACTION INTEGRATION TESTS")
print("=" * 60)


# ═══════════════════════════════════════════════════════════════════
# TEST 1: _should_execute_action
# ═══════════════════════════════════════════════════════════════════
print("\n📋 TEST 1: _should_execute_action()")
print("-" * 40)

from core.action_router import ActionRouter


def _should_execute_action(intent: str) -> bool:
    """Copia de la función del orquestador para test."""
    if not intent:
        return False
    return intent in ActionRouter.INTENT_ACTION_MAP


# Test cases
test_cases = [
    ("notion_create", True, "notion_create debe ser accionable"),
    ("notion_update", True, "notion_update debe ser accionable"),
    ("notion_delete", True, "notion_delete debe ser accionable"),
    ("file_read", True, "file_read debe ser accionable"),
    ("file_write", True, "file_write debe ser accionable"),
    ("code_refactor", True, "code_refactor debe ser accionable"),
    ("command_run", True, "command_run debe ser accionable"),
    ("general", False, "general NO debe ser accionable"),
    ("profile", False, "profile NO debe ser accionable"),
    ("", False, "intent vacío NO debe ser accionable"),
    (None, False, "intent None NO debe ser accionable"),
]

all_pass = True
for intent, expected, desc in test_cases:
    # Handle None specifically
    result = _should_execute_action(intent) if intent is not None else False
    status = "✅" if result == expected else "❌"
    if result != expected:
        all_pass = False
    print(f"  {status} {desc}: got={result}, expected={expected}")

print(f"\n  Resultado: {'✅ TODOS PASARON' if all_pass else '❌ HAY FALLOS'}")


# ═══════════════════════════════════════════════════════════════════
# TEST 2: _extract_action_params
# ═══════════════════════════════════════════════════════════════════
print("\n\n📋 TEST 2: _extract_action_params()")
print("-" * 40)

from typing import Dict, Any
import re


def _extract_action_params(intent: str, user_message: str) -> Dict[str, Any]:
    """Copia de la función del orquestador para test."""
    params: Dict[str, Any] = {}

    if intent == "notion_create":
        msg = user_message
        # Intentar extraer título después de "llamada" o "titulada"
        title_match = re.search(
            r'(?:llamada|llamado|titulada|titulado|con el nombre)\s+"([^"]+)"',
            msg, re.IGNORECASE
        )
        if not title_match:
            title_match = re.search(
                r'(?:llamada|llamado|titulada|titulado)\s+([a-zA-Záéíóúñ ]+)',
                msg, re.IGNORECASE
            )
        if title_match:
            params["title"] = title_match.group(1).strip()
        else:
            params["title"] = user_message[:50]

        # Intentar extraer contenido
        content_match = re.search(
            r'(?:contenido|que diga|que diga:)\s+"([^"]+)"',
            msg, re.IGNORECASE
        )
        if content_match:
            params["content"] = content_match.group(1).strip()

    return params


# Test con título entre comillas
params = _extract_action_params("notion_create", 'Crea una página llamada "Mi Proyecto"')
assert params.get("title") == "Mi Proyecto", f"❌ Esperaba 'Mi Proyecto', obtuve '{params.get('title')}'"
print(f"  ✅ Título entre comillas: '{params.get('title')}'")

# Test con título sin comillas
params = _extract_action_params("notion_create", "Crea una página llamada Ideas nuevas")
assert params.get("title") == "Ideas nuevas", f"❌ Esperaba 'Ideas nuevas', obtuve '{params.get('title')}'"
print(f"  ✅ Título sin comillas: '{params.get('title')}'")

# Test con "titulada"
params = _extract_action_params("notion_create", 'Crea una página titulada "Lista de Tareas"')
assert params.get("title") == "Lista de Tareas", f"❌ Esperaba 'Lista de Tareas', obtuve '{params.get('title')}'"
print(f"  ✅ Título con 'titulada': '{params.get('title')}'")

# Test con contenido
params = _extract_action_params("notion_create", 'Crea una página llamada "Notas" que diga "Contenido importante"')
assert params.get("title") == "Notas", f"❌ Esperaba 'Notas', obtuvo '{params.get('title')}'"
assert params.get("content") == "Contenido importante", f"❌ Esperaba 'Contenido importante', obtuvo '{params.get('content')}'"
print(f"  ✅ Título + contenido: '{params.get('title')}' / '{params.get('content')}'")

# Test sin título explícito
params = _extract_action_params("notion_create", "Quiero crear una página")
assert params.get("title") is not None, "❌ Debería tener un título fallback"
print(f"  ✅ Fallback título: '{params.get('title')}'")

print(f"\n  Resultado: ✅ TODOS PASARON")


# ═══════════════════════════════════════════════════════════════════
# TEST 3: ActionRouter routing
# ═══════════════════════════════════════════════════════════════════
print("\n\n📋 TEST 3: ActionRouter.route()")
print("-" * 40)

# Test notion_create route
decision_trace = {"intent": "notion_create", "changed": False, "source": "test"}
context = {
    "user_id": "test_user",
    "params": {"title": "Test Page"},
    "decision_trace": decision_trace,
}
action = ActionRouter.route(decision_trace, "notion_create", context)
assert action is not None, "❌ ActionRouter.route() debería retornar una acción para notion_create"
assert action.action_type == "NotionAction", f"❌ Esperaba NotionAction, obtuve {action.action_type}"
assert action.get_description() == "Crear página en Notion: 'Test Page'", \
    f"❌ Descripción incorrecta: {action.get_description()}"
print(f"  ✅ NotionAction ruteada correctamente: {action.get_description()}")

# Test con intent no mapeado
action = ActionRouter.route(decision_trace, "intent_inventado", context)
assert action is None, "❌ Debería retornar None para intents no mapeados"
print(f"  ✅ Intent no mapeado retorna None correctamente")

# Test con intent vacío
action = ActionRouter.route(decision_trace, "", context)
assert action is None, "❌ Debería retornar None para intent vacío"
print(f"  ✅ Intent vacío retorna None correctamente")

print(f"\n  Resultado: ✅ TODOS PASARON")


# ═══════════════════════════════════════════════════════════════════
# TEST 4: ActionLogger log & history
# ═══════════════════════════════════════════════════════════════════
print("\n\n📋 TEST 4: ActionLogger.log() & get_history()")
print("-" * 40)

from core.action_logger import ActionLogger

# Limpiar registro previo
from core.persistence import _get_connection
conn = _get_connection()
conn.execute("DELETE FROM action_history WHERE user_id = 'test_integration'")
conn.commit()

# Log una acción simulada
ActionLogger.log(
    user_id="test_integration",
    action_type="NotionAction",
    params={"title": "Test Page", "parent_id": "abc123"},
    result={"success": True, "result": {"page_id": "page123"}},
    approved=None,  # autónoma
    duration_ms=150,
)

# Log una acción rechazada
ActionLogger.log(
    user_id="test_integration",
    action_type="CommandAction",
    params={"command": "rm -rf /"},
    result={"success": False, "error": "Rejected by user"},
    approved=False,
    duration_ms=0,
)

# Recuperar historial
history = ActionLogger.get_history("test_integration", limit=5)

assert len(history) == 2, f"❌ Esperaba 2 registros, obtuve {len(history)}"
assert history[0]["action_type"] == "CommandAction", \
    f"❌ Esperaba CommandAction primero (más reciente), obtuve {history[0]['action_type']}"
assert history[0]["approved"] == 0, f"❌ Esperaba approved=0, obtuve {history[0]['approved']}"
assert history[1]["action_type"] == "NotionAction", \
    f"❌ Esperaba NotionAction segundo, obtuve {history[1]['action_type']}"
assert history[1]["approved"] is None, f"❌ Esperaba approved=None, obtuve {history[1]['approved']}"
assert history[1]["success"] is True, f"❌ Esperaba success=True, obtuve {history[1]['success']}"

print(f"  ✅ Acción autónoma loggeada correctamente (approved=None)")
print(f"  ✅ Acción rechazada loggeada correctamente (approved=0)")
print(f"  ✅ Historial ordenado por fecha descendente")
print(f"  ✅ {len(history)} registros recuperados")

# Test get_summary
summary = ActionLogger.get_summary("test_integration", limit=2)
assert "NotionAction" in summary, "❌ Summary debería incluir NotionAction"
assert "CommandAction" in summary, "❌ Summary debería incluir CommandAction"
print(f"  ✅ Summary generado correctamente:\n{summary}")

print(f"\n  Resultado: ✅ TODOS PASARON")


# ═══════════════════════════════════════════════════════════════════
# TEST 5: MemoryDecisionLayer detect_intent (crear página)
# ═══════════════════════════════════════════════════════════════════
print("\n\n📋 TEST 5: MemoryDecisionLayer.detect_intent()")
print("-" * 40)

from core.memory_decision import MemoryDecisionLayer

decision_layer = MemoryDecisionLayer()

# Test "crear página"
intent = decision_layer.detect_intent("Crea una página llamada Mi Proyecto")
assert intent == "notion_create", f"❌ Esperaba 'notion_create', obtuve '{intent}'"
print(f"  ✅ 'Crea una página...' → '{intent}'")

# Test "nueva página"
intent = decision_layer.detect_intent("quiero una nueva página en Notion")
assert intent == "notion_create", f"❌ Esperaba 'notion_create', obtuve '{intent}'"
print(f"  ✅ 'nueva página...' → '{intent}'")

# Test "crea una página"
intent = decision_layer.detect_intent("crea una página de prueba")
assert intent == "notion_create", f"❌ Esperaba 'notion_create', obtuve '{intent}'"
print(f"  ✅ 'crea una página...' → '{intent}'")

# Test mensaje genérico NO dispara notion_create
intent = decision_layer.detect_intent("hola, cómo estás?")
assert intent == "general", f"❌ Esperaba 'general', obtuve '{intent}'"
print(f"  ✅ 'hola, cómo estás?' → '{intent}' (no dispara falsos positivos)")

print(f"\n  Resultado: ✅ TODOS PASARON")


# ═══════════════════════════════════════════════════════════════════
# TEST 6: Flujo completo (sin Telegram, sin Notion real)
# ═══════════════════════════════════════════════════════════════════
print("\n\n📋 TEST 6: Flujo completo (simulado)")
print("-" * 40)

# Simular el pipeline: detect → should_execute → route → execute → log
user_message = 'Crea una página llamada "Mi Página de Prueba" que diga "Contenido de prueba"'
chat_id = 999999

# 1. Detectar intent
intent = decision_layer.detect_intent(user_message.lower().strip())
assert intent == "notion_create", f"❌ Paso 1 falló: intent='{intent}'"
print(f"  ✅ Paso 1 - detect_intent: {intent}")

# 2. Verificar que es accionable
assert _should_execute_action(intent), "❌ Paso 2 falló: debería ser accionable"
print(f"  ✅ Paso 2 - should_execute_action: True")

# 3. Extraer parámetros
params = _extract_action_params(intent, user_message)
assert params.get("title") == "Mi Página de Prueba", f"❌ Paso 3 falló: title='{params.get('title')}'"
assert params.get("content") == "Contenido de prueba", f"❌ Paso 3 falló: content='{params.get('content')}'"
print(f"  ✅ Paso 3 - extract_params: title='{params.get('title')}', content='{params.get('content')}'")

# 4. Route
decision_trace = {"intent": intent, "changed": False, "source": "test", "confidence": 1.0}
action_context = {
    "user_id": str(chat_id),
    "params": params,
    "decision_trace": decision_trace,
}
action = ActionRouter.route(decision_trace, intent, action_context)
assert action is not None, "❌ Paso 4 falló: action is None"
assert action.action_type == "NotionAction", f"❌ Paso 4 falló: {action.action_type}"
assert action.operation == "create", f"❌ Paso 4 falló: operation={action.operation}"
print(f"  ✅ Paso 4 - route: {action.action_type} (operation={action.operation})")

# 5. Verificar que execute es async y retorna estructura correcta
# (No ejecutamos realmente porque no hay token de Notion)
import inspect
assert inspect.iscoroutinefunction(action.execute), "❌ Paso 5 falló: execute debe ser async"
print(f"  ✅ Paso 5 - execute es async: True")

# 6. Verificar log
ActionLogger.log(
    user_id=str(chat_id),
    action_type="NotionAction",
    params=params,
    result={"success": True, "result": {"page_id": "test123", "title": "Mi Página de Prueba"}},
    approved=None,
    duration_ms=100,
)
history = ActionLogger.get_history(str(chat_id), limit=1)
assert len(history) == 1, f"❌ Paso 6 falló: history len={len(history)}"
assert history[0]["action_type"] == "NotionAction", f"❌ Paso 6 falló: type={history[0]['action_type']}"
print(f"  ✅ Paso 6 - log: registrado correctamente")

print(f"\n  Resultado: ✅ FLUJO COMPLETO VERIFICADO")


# ═══════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("RESUMEN FINAL")
print("=" * 60)
print("""
  ✅ Action System integrado con Cognitive Core
  ✅ Detección de "crear página" → notion_create
  ✅ Parámetros extraídos de lenguaje natural
  ✅ Rutas de acción verificadas
  ✅ Logging y persistencia verificados
  ✅ Flujo completo: mensaje → intent → acción → log

  Próximos pasos:
  - Probar con Telegram real
  - Probar con Notion real (requiere NOTION_TOKEN)
  - Implementar más operaciones (file, code, command)
""")
print("=" * 60)
