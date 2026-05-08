"""
Prueba de la deteccion de intents expandida en MemoryDecisionLayer.
Verifica que los nuevos intents se detecten correctamente y sean
compatibles con ActionRouter.INTENT_ACTION_MAP.

Ejecutar: py -3 test_intent_detection.py
"""
from core.memory_decision import MemoryDecisionLayer
from core.action_router import ActionRouter

layer = MemoryDecisionLayer()

test_cases = [
    # NOTION (expandido)
    ("crear una pagina en notion", "notion_create"),
    ("nueva pagina para mis notas", "notion_create"),
    ("crea una pagina de bienvenida", "notion_create"),
    ("Crear pagina", "notion_create"),
    ("actualiza pagina de bienvenida", "notion_update"),
    ("actualiza la pagina de configuracion", "notion_update"),
    ("modifica pagina de inicio", "notion_update"),
    ("modifica la pagina de configuracion", "notion_update"),
    ("edita la pagina de inicio", "notion_update"),
    ("actualiza notion con estos datos", "notion_update"),
    ("elimina pagina temporal", "notion_delete"),
    ("elimina la pagina vieja", "notion_delete"),
    ("borra pagina", "notion_delete"),
    ("borra esa pagina", "notion_delete"),
    ("elimina notion con ese id", "notion_delete"),

    # CODE GENERATE
    ("haz un componente de react", "code_generate"),
    ("genera codigo para un endpoint", "code_generate"),
    ("crea un componente de login", "code_generate"),
    ("escribe codigo para una api", "code_generate"),
    ("genera componente de sidebar", "code_generate"),
    ("write code for a module", "code_generate"),
    ("create a component in react", "code_generate"),

    # CODE REFACTOR
    ("refactoriza este modulo", "code_refactor"),
    ("refactorizar el codigo de auth", "code_refactor"),
    ("refactor el controlador", "code_refactor"),
    ("mejora este codigo por favor", "code_refactor"),
    ("optimiza codigo de consultas", "code_refactor"),
    ("limpia codigo de la funcion", "code_refactor"),

    # CODE DEBUG
    ("debug esto no funciona", "code_debug"),
    ("debug este codigo tiene errores", "code_debug"),
    ("arregla este codigo tiene bugs", "code_debug"),
    ("depura el error de conexion", "code_debug"),
    ("corrige el error de login", "code_debug"),
    ("debug this function", "code_debug"),

    # FILE WRITE
    ("crea un archivo de configuracion", "file_write"),
    ("escribe un archivo readme", "file_write"),
    ("genera un archivo de texto", "file_write"),
    ("guarda archivo de logs", "file_write"),
    ("create a file for data", "file_write"),

    # FILE READ
    ("lee este archivo JSON", "file_read"),
    ("abre archivo de logs", "file_read"),
    ("muestra archivo de configuracion", "file_read"),
    ("que contiene el archivo temporal", "file_read"),
    ("leer archivo de configuracion", "file_read"),
    ("read this file for me", "file_read"),

    # COMMAND RUN
    ("ejecuta el servidor", "command_run"),
    ("lanza la aplicacion", "command_run"),
    ("run this script", "command_run"),
    ("corre el comando de build", "command_run"),
    ("ejecutar tests unitarios", "command_run"),

    # LEGACY: ACTION
    ("como se escribe un test", "action"),
    ("how to create a function", "action"),

    # LEGACY: PROFILE
    ("que sabes de mi perfil", "profile"),
    ("sobre mi", "profile"),

    # LEGACY: GENERAL (fallback)
    ("hola como estas", "general"),
    ("buenos dias", "general"),
]

passed = 0
failed = 0
errors = []

print("=" * 70)
print("  PRUEBAS DE DETECCION DE INTENT")
print("  Sistema de deteccion expandido para ActionRouter")
print("=" * 70)

for input_text, expected in test_cases:
    result = layer.detect_intent(input_text)
    if result == expected:
        passed += 1
    else:
        failed += 1
        errors.append((input_text, expected, result))

if errors:
    print()
    print("  FALLOS:")
    print()
    for inp, exp, res in errors:
        print(f"     INPUT:    \"{inp}\"")
        print(f"     Esperado: {exp}")
        print(f"     Obtenido: {res}")
        print()
else:
    print()
    print("  TODAS LAS PRUEBAS PASARON")
    print()

print("=" * 70)
print(f"  Resultados: {passed} pasaron, {failed} fallaron de {len(test_cases)}")
print("=" * 70)

print()
print("=" * 70)
print("  MAPA DE INTENTS: DETECTABLE vs ROUTER")
print("=" * 70)

frases_prueba = [
    "crear pagina", "actualiza pagina", "elimina pagina",
    "haz un componente", "refactoriza", "debug esto",
    "crea un archivo", "lee este archivo", "ejecuta",
]
detectable = set()
for p in frases_prueba:
    detectable.add(layer.detect_intent(p))

available = set(ActionRouter.get_available_intents())

print(f"  Intents detectables por detect_intent():")
for i in sorted(detectable):
    print(f"    - {i}")
print()
print(f"  Intents registrados en ActionRouter:")
for i in sorted(available):
    print(f"    - {i}")
print()

missing = available - detectable
extra = detectable - available

if missing:
    print(f"  Intents en router SIN deteccion aun:")
    for i in sorted(missing):
        print(f"    - {i}")
    print()

if extra:
    print(f"  Intents detectables SIN mapeo en router (nuevos):")
    for i in sorted(extra):
        print(f"    - {i}")
    print()

if not missing and not extra:
    print("  Todos los intents del router tienen deteccion o viceversa")
    print()

print("=" * 70)
print("  COMPATIBILIDAD: detect_intent() -> ActionRouter.route()")
print("=" * 70)
compatibles = detectable & available
for i in sorted(compatibles):
    action_class = ActionRouter.INTENT_ACTION_MAP[i]
    print(f"  \"{i}\" -> {action_class.__name__}")
