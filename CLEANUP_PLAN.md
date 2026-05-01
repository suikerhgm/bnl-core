# 🧹 CLEANUP PLAN — Plan de Limpieza para NexusAgentes

> **Fase 3 de 5** | Generado: 29/04/2026  
> Basado en STRUCTURE_REPORT.md | Prioriza cambios **seguros y reversibles**

---

## 📋 Guía de Ejecución

| Símbolo | Significado | Acción |
|---------|-------------|--------|
| ✅ | **SEGURO** | Eliminar/Modificar sin riesgo — no hay imports activos |
| ⚠️ | **PRECAUCIÓN** | Verificar dependencias antes de modificar |
| 🔴 | **NO TOCAR** | Requiere refactor mayor — NO hacer en Fase 4 |

---

## LOTE 1: ELIMINACIÓN DE CÓDIGO MUERTO (✅ Seguro — 4 sub-tareas)

### Tarea 1.1 — Eliminar Zombie Agents
**Archivos:**
- `agents/planner.py` (18 líneas, placeholder)
- `agents/executor.py` (27 líneas, placeholder)
- `agents/blueprint.py` (22 líneas, placeholder)

**Verificación:** Buscar imports → `grep -r "agents\.\(planner\|executor\|blueprint\)" .` — ningún resultado esperado.

**Comando:**
```bash
rm agents/planner.py agents/executor.py agents/blueprint.py
rmdir agents\__pycache__  # clean cache
```

**Riesgo:** ✅ NINGUNO — nadie importa estos archivos.

---

### Tarea 1.2 — Eliminar Standalone App Muerta
**Archivos:**
- `nexus_notion_tools.py` (847 líneas, FastAPI standalone)

**Verificación:** Buscar imports → `grep -r "nexus_notion_tools" .` — ningún resultado esperado.

**Comando:**
```bash
rm nexus_notion_tools.py
```

**Riesgo:** ✅ NINGUNO — nadie importa. La funcionalidad build_app existe en `services/build_service.py` (mejor implementada).

---

### Tarea 1.3 — Eliminar Scripts Huérfanos
**Archivos:**
- `configure_n8n.py` (141 líneas, n8n setup de arquitectura anterior)
- `workflow_backup.json` (workflow n8n de arquitectura anterior)
- `scripts/__init__.py` (archivo vacío)

**Comando:**
```bash
rm configure_n8n.py workflow_backup.json scripts/__init__.py
```

**Nota:** Si se desea preservar `configure_n8n.py` como referencia histórica, moverlo a `archive/` en vez de eliminar.

**Riesgo:** ✅ NINGUNO — nadie importa, arquitectura obsoleta.

---

### Tema 1.4 — Eliminar package.json (Node.js)
**Archivo:**
- `package.json` (dependencias whatsapp-web.js, no usado)

**Comando:**
```bash
rm package.json
# Si existe node_modules/:
rm -rf node_modules
```

**Riesgo:** ✅ NINGUNO — proyecto 100% Python.

---

## LOTE 2: CONFIGURACIÓN Y DEPENDENCIAS (✅ Seguro — 2 sub-tareas)

### Tarea 2.1 — Ampliar .gitignore
**Agregar al final de `.gitignore`:**
```
# NexusAgentes specific
nexus_state.db
nexus_state.db-journal
chat_states.json
*.db
*.db-journal

# Test artifacts
test_*.py
!test_*.py  # maybe keep if needed
tests/
test_ui.html

# Node.js (legacy)
node_modules/
package.json
package-lock.json

# Legacy files (moved/archived)
archive/
```

**Riesgo:** ✅ NINGUNO — solo afecta control de versiones.

---

### Tarea 2.2 — Completar requirements.txt
**Contenido final:**
```txt
fastapi
uvicorn[standard]
python-dotenv
httpx
groq
python-telegram-bot
notion-client
pydantic
google-genai
openai
```

**Riesgo:** ✅ NINGUNO — solo documentación de dependencias existentes.

---

## LOTE 3: LIMPIEZA DE IMPORTS MUERTOS (✅ Seguro — 1 sub-tarea)

### Tarea 3.1 — Eliminar MemoryDecider de conversation_orchestrator.py
**Archivo:** `orchestrators/conversation_orchestrator.py`

**Cambios:**
1. Eliminar línea 28: `from core.memory_decider import MemoryDecider`
2. Eliminar línea 65: `_memory_decider = MemoryDecider()`

**Riesgo:** ✅ NINGUNO — `_memory_decider` nunca se usa.

---

## LOTE 4: REFACTOR BAJO RIESGO (⚠️ Precaución) → PLANIFICAR PARA FUTURO

### Tarea 4.1 — Unificar Notion Implementations
**Archivos involucrados:**
- `services/notion_service.py` (278 líneas) → **ELIMINAR** después de migrar
- `core/notion_gateway.py` (317 líneas) → **MANTENER** (async, más completo)

**Dependencias que usan `services/notion_service.py`:**
- `routes/notion_routes.py` → `from services.notion_service import notion_search, ...`
- `routes/build_routes.py` → `from services.notion_service import notion_search`
- `services/build_service.py` → `from services.notion_service import notion_search`

**Afecta:** 3 archivos → cambiar imports a `core.notion_gateway`.

**Riesgo:** ⚠️ MEDIO — migrar de sync a async requiere cambiar firmas.

**NO HACER en Fase 4** — requiere refactor.

---

### Tarea 4.2 — Unificar Routes
**Archivos involucrados:**
- `routes/notion_routes.py` → migrar a `app/routes/notion_routes.py`
- `routes/build_routes.py` → migrar a `app/routes/build_routes.py`
- `routes/__init__.py` → eliminar

**Dependencias:** Verificar si el `app/main.py` o `app/__init__.py` importa routes/ o app/routes/.

**NO HACER en Fase 4** — requiere verificación de entrypoints.

---

### Tarea 4.3 — Mover Tests a Directorio Propio
**Archivos:** 18 archivos `test_*.py` en la raíz → mover a `tests/`

**Comando:**
```bash
mkdir tests
mv test_*.py tests/
mv test_ui.html tests/
```

**Riesgo:** ✅ BAJO — si se actualiza el entrypoint o se usa `pytest tests/`.

---

### Tarea 4.4 — Resolver patterns type conflict
**Archivo:** `orchestrators/conversation_orchestrator.py`, líneas 392-398

**Problema:** `identity["patterns"]` se trata como `List[str]` pero `persisted_identity["patterns"]` puede ser `Dict[str, Dict]`.

**Solución:** Normalizar a un tipo consistente (sugerencia: `Dict[str, float]` para pesos de patrones).

**NO HACER en Fase 4** — requiere análisis profundo del learning loop.

---

## 📊 RESUMEN DE EJECUCIÓN PARA FASE 4

| # | Tarea | Archivos Afectados | Riesgo | ¿Hacer en Fase 4? |
|---|-------|-------------------|--------|-------------------|
| 1.1 | Eliminar Zombie Agents | `agents/planner.py`, `executor.py`, `blueprint.py` | ✅ Seguro | ✅ **SÍ** |
| 1.2 | Eliminar nexus_notion_tools.py | `nexus_notion_tools.py` | ✅ Seguro | ✅ **SÍ** |
| 1.3 | Eliminar scripts huérfanos | `configure_n8n.py`, `workflow_backup.json`, `scripts/__init__.py` | ✅ Seguro | ✅ **SÍ** |
| 1.4 | Eliminar package.json | `package.json`, `node_modules/` | ✅ Seguro | ✅ **SÍ** |
| 2.1 | Ampliar .gitignore | `.gitignore` | ✅ Seguro | ✅ **SÍ** |
| 2.2 | Completar requirements.txt | `requirements.txt` | ✅ Seguro | ✅ **SÍ** |
| 3.1 | Eliminar MemoryDecider import | `orchestrators/conversation_orchestrator.py` | ✅ Seguro | ✅ **SÍ** |
| 4.1 | Unificar Notion | `services/notion_service.py` | ⚠️ Medio | ❌ **NO** |
| 4.2 | Unificar Routes | `routes/*` | ⚠️ Medio | ❌ **NO** |
| 4.3 | Mover tests | 18 archivos | ✅ Bajo | ❌ **OPCIONAL** |
| 4.4 | patterns type conflict | `conversation_orchestrator.py` | ⚠️ Medio | ❌ **NO** |

---

## ✅ VERIFICACIÓN POST-CLEANUP (para después de Fase 4)

Después de ejecutar los cambios, verificar:

```bash
# 1. Verificar que no hay imports rotos
python -c "from orchestrators.conversation_orchestrator import process_message; print('✅ conversation_orchestrator OK')"
python -c "from core.notion_gateway import notion_search; print('✅ notion_gateway OK')"
python -c "from core.behavior_pipeline import BehaviorPipeline; print('✅ behavior_pipeline OK')"
python -c "from core.persistence import load_identity, save_identity; print('✅ persistence OK')"
python -c "from core.ai_cascade import call_ai_with_fallback; print('✅ ai_cascade OK')"

# 2. Verificar que los archivos eliminados no son necesarios
grep -r "nexus_notion_tools\|configure_n8n\|agents\.planner\|agents\.executor\|agents\.blueprint" . --include="*.py"

# 3. Verificar estructura del proyecto
ls -la
```

---

*Fin de CLEANUP_PLAN.md — Listo para Fase 4: Safe Cleanup*
