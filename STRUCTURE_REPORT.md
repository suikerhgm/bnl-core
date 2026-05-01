# 🏗️ STRUCTURE REPORT — Auditoría Estructural de NexusAgentes

> **Fase 2 de 5** | Generado: 29/04/2026  
> Propósito: Detectar código duplicado, muerto, inconsistente, mal ubicado y riesgos arquitectónicos.

---

## 📋 Resumen de Hallazgos

| Categoría | Cantidad | Riesgo |
|-----------|----------|--------|
| 🔴 Código duplicado | 5 instancias | ALTO |
| ⚰️ Código muerto (archivos) | 5 archivos | MEDIO |
| 🧟 Código muerto (imports/funciones) | 3+ instancias | BAJO |
| 🌀 Nombres inconsistentes | 5+ instancias | BAJO |
| 🏚️ Arquitecturas mezcladas | 4 instancias | ALTO |
| 📦 Archivos mal ubicados | 4 ubicaciones | BAJO |
| ⚠️ Dependencias faltantes | 2+ instancias | MEDIO |

---

## 1. 🔴 CÓDIGO DUPLICADO

### 1.1 Dual Notion Implementation

```
core/notion_gateway.py  (317 líneas, async httpx)       ← MODERNA
services/notion_service.py (278 líneas, sync SDK)        ← LEGACY
```

**Funciones duplicadas (casi idénticas):**

| Función | core/notion_gateway | services/notion_service |
|---------|---------------------|------------------------|
| `notion_search(query)` | ✅ Async via httpx | ✅ Sync via notion_client.SDK |
| `notion_fetch(page_id)` | ✅ Async via httpx | ✅ Sync via notion_client.SDK |
| `notion_create(parent_id, title, content)` | ✅ Async via httpx | ✅ Sync via notion_client.SDK |
| `_extract_page_title(page)` | ✅ | ✅ (idéntica lógica) |
| `_block_to_markdown(block)` | ✅ | ✅ (idéntica lógica) |
| `_get_all_blocks(page_id)` | ✅ | ✅ (idéntica lógica) |
| `_blocks_to_markdown(blocks)` | ✅ | ✅ (idéntica lógica) |
| `_markdown_to_notion_blocks(text)` | ✅ | ✅ (idéntica lógica) |

**Diferencia clave:**
- `core/notion_gateway.py` usa `httpx.AsyncClient` → funciones `async`
- `services/notion_service.py` usa `notion_client.Client` SDK oficial → funciones sincrónicas
- `core/notion_gateway.py` tiene extras: `notion_update()`, `_notion_query_database()`, `_fuzzy_match_title()`, `build_notion_blocks()`, `clean_page_id()`
- `services/notion_service.py` es funcionalmente un subconjunto más simple

**Riesgo: ALTO** — Mantener ambos causa divergencia, bugs de sincronización y confusión.

---

### 1.2 Triple Notion Route Layer

```
routes/notion_routes.py        (102 líneas, sync)      ← LEGACY
routes/build_routes.py         (131 líneas, sync)      ← LEGACY  
nexus_notion_tools.py          (847 líneas, standalone) ← LEGACY MUERTO
app/routes/telegram_routes.py  (existente)             ← MODERNO?
```

- `routes/notion_routes.py` y `routes/build_routes.py` **son gemelos funcionales** de partes de `nexus_notion_tools.py`
- `nexus_notion_tools.py` es una **aplicación FastAPI independiente y completa** (con CORS, auth, modelos Pydantic, 5 endpoints) — un proyecto entero duplicado dentro del proyecto
- Los modelos `SearchRequest`, `FetchRequest`, `CreateRequest` existen en:
  - `models/schemas.py` (compartido)
  - `nexus_notion_tools.py` (duplicado inline)
  - `models/schemas.py` tiene `BuildAppRequest`, `PlanResponse`, etc. — joyería compartible

**Riesgo: ALTO** — `nexus_notion_tools.py` es un proyecto fantasma de 847 líneas. Compite con routes/, tiene su propia versión de todo.

---

### 1.4 Dual Entry Points (Telegram)

```
nexus_bot.py  (337 líneas, FastAPI webhook)    ← PRODUCCIÓN
app/main.py   (93 líneas, PTB polling)         ← DESARROLLO
```

- `nexus_bot.py`: Servidor web con webhook de Telegram en puerto 8001
- `app/main.py`: Aplicación de polling directo de python-telegram-bot
- **No deberían ejecutarse simultáneamente** (competirían por el webhook)
- Comparten el mismo `process_message()` del orquestador

**Riesgo: MEDIO** — Confusión sobre cuál es el entrypoint correcto. Ambos funcionales pero arquitectónicamente diferentes.

---

### 1.5 Build App Duplicado

```
services/build_service.py  (485 líneas)          ← VERSIÓN MODERNA (con filtrado + fallback)
nexus_notion_tools.py      (847 líneas, líneas 519-697) ← COPIA EXACTA
```

Las funciones `generate_blueprint()`, `plan_tasks()`, `build_app()` existen en AMBOS archivos. La versión en `services/build_service.py` tiene lógica de filtrado y fallback inteligente; la de `nexus_notion_tools.py` es más simple y antigua.

---

## 2. ⚰️ CÓDIGO MUERTO — Archivos completos

### 2.1 Zombie Agents (`agents/`)

| Archivo | Líneas | ¿Importado por alguien? | Decisión |
|---------|--------|------------------------|----------|
| `agents/planner.py` | 18 | ❌ NO | ✅ SAFE TO REMOVE |
| `agents/executor.py` | 27 | ❌ NO | ✅ SAFE TO REMOVE |
| `agents/blueprint.py` | 22 | ❌ NO | ✅ SAFE TO REMOVE |

Los tres son placeholders con docstrings que dicen "En futuras versiones...". La lógica real existe en `services/build_service.py`.

---

### 2.2 Zombie Standalone App

| Archivo | Líneas | ¿Importado por alguien? | Decisión |
|---------|--------|------------------------|----------|
| `nexus_notion_tools.py` | 847 | ❌ NO | ✅ SAFE TO REMOVE |

Entera aplicación FastAPI independiente con pipeline build_app completo. No usada por el sistema actual (que usa `nexus_bot.py` o `app/main.py`).

---

### 2.3 Zombie Scripts

| Archivo | Líneas | ¿Importado por alguien? | Decisión |
|---------|--------|------------------------|----------|
| `configure_n8n.py` | 141 | ❌ NO | ✅ SAFE TO REMOVE |
| `workflow_backup.json` | — | ❌ NO | ✅ SAFE TO REMOVE |
| `scripts/__init__.py` | 0 | ❌ NO | ✅ SAFE TO REMOVE |

`configure_n8n.py` es de la arquitectura anterior (Leo → n8n → Gemini → Python), obsoleta desde v3.0.

---

### 2.4 Zombie Dependencies

| Archivo | Propósito | Decisión |
|---------|-----------|----------|
| `package.json` | Dependencias Node.js para `whatsapp-web.js` | ✅ SAFE TO REMOVE |

**Proyecto 100% Python.** `package.json` con `whatsapp-web.js` y `qrcode-terminal` no tiene propósito aquí. Si existe `node_modules/`, puede eliminarse.

---

## 3. 🧟 CÓDIGO MUERTO — Dentro de archivos

### 3.1 MemoryDecider — Nunca llamado

**Archivo:** `orchestrators/conversation_orchestrator.py`

```python
# Línea 28: Importado
from core.memory_decider import MemoryDecider

# Línea 65: Instanciado como singleton
_memory_decider = MemoryDecider()
```

`_memory_decider` **NUNCA se usa** en ninguna parte de `process_message()` ni en `_process_message_inner()`. Fue planeado para decidir almacenamiento en memoria pero `_memory_manager.save_episode()` se llama directamente.

---

### 3.2 `c` — Archivo huérfano en la raíz

En la lista de archivos del proyecto aparece un archivo llamado `c` en la raíz. Sin extensión, sin propósito identificable.

**Decisión:** ❓ NEEDS REVIEW (verificar antes de eliminar)

---

## 4. 🌀 INCONSISTENCIAS DE NOMBRES

### 4.1 `patterns` — Conflicto de tipos

| Componente | Tipo de `patterns` | 
|-----------|-------------------|
| `memory_identity.py` → `MemoryIdentityLayer.build_identity()` | `List[str]` |
| `memory_pattern_integrator.py` → `MemoryPatternIntegrator` | `Dict[str, Dict]` |

En `conversation_orchestrator.py` líneas 393-398:
```python
identity.setdefault("patterns", [])       # ← Espera List[str]
for key in persisted_pattern_keys:
    if key not in identity["patterns"]:    # ← Trata List como si fuera Dict
        identity["patterns"].append(key)   # ← append en contexto de dict keys
```

**Esto es un bug funcional.** El merge de patrones persistentes con identidad local mezcla semántica de `List` y `Dict`.

**Riesgo: MEDIO** — Puede causar errores silenciosos en el learning loop.

---

### 4.2 Nombres de variables inconsistentes

| Ubicación | Inconsistencia |
|-----------|---------------|
| `services/notion_service.py` | `clean_id` para page_id normalizada |
| `nexus_notion_tools.py` | `clean_id` y `clean_parent_id` |
| `core/notion_gateway.py` | `clean_page_id()` como función separada |
| Todo el proyecto | Mezcla EN/ES en nombres de variables y comentarios |

---

### 4.3 Mezcla de idiomas

El proyecto mezcla **inglés y español** en todas partes:
- Nombres de funciones: `_extract_page_title()` (EN) vs `plan_tasks()` (EN) vs `_generar_blueprint` (ES)
- Comentarios: Mitad en español, mitad en inglés
- Docstrings: Mayormente español
- Código: `chat_id`, `user_message`, `plan_id` (EN) pero `respuesta`, `tareas` (ES)

**Riesgo: BAJO** — No afecta funcionalidad pero dificulta el mantenimiento.

---

## 5. 🏚️ ARQUITECTURAS MEZCLADAS

### 5.1 Async vs Sync

```
core/                       → Async (httpx, asyncio)     ← MODERNO
orchestrators/              → Async                      ← MODERNO
services/ + routes/         → Sync (notion_client.SDK)   ← LEGACY
app/services/telegram_service.py → Async + imports sync  ← PUENTE
```

**Problema:** `orchestrators/cleaning_orchestrator.py` importa de AMBOS mundos:
```python
from core.notion_gateway import notion_search, ...  # Async
from app.services.notion_cleaner_agent import NotionCleanerAgent  # Sync wrapper
```

---

### 5.2 Legacy Stack vs Modern Stack

**Stack moderno (activo):**
- `core/` → async httpx, memory layers, behavior pipeline
- `orchestrators/` → async process_message, cleaning flow
- SQLite persistence (`core/persistence.py`)

**Stack legacy (potencialmente inactivo):**
- `services/` + `routes/` → sync notion_client, build_app, notion CRUD
- `app/services/telegram_service.py` → god file puente
- JSON state manager (`core/state_manager.py`)

---

### 5.3 God File: `app/services/telegram_service.py`

**152 líneas**, pero:
- Importa desde `core.state_manager`, `core.ai_cascade`, `core.notion_gateway`, `core.backend_client`, `core.formatters`, `core.tools`
- Importa desde `orchestrators.conversation_orchestrator`
- Contiene `send_telegram_message()`, `handle_telegram_update()`
- **Es el punto de unión entre dos mundos arquitectónicos**

---

### 5.4 Import Circular en Potencia

`app/services/telegram_service.py` → importa → `orchestrators.conversation_orchestrator`  
`orchestrators/cleaning_orchestrator.py` → importa → `app.services.notion_cleaner_agent` → importa → `app.services.telegram_service`

Esto crea una **cadena de dependencias circulares potenciales**:
```
telegram_service → conversation_orchestrator → cleaning_orchestrator → notion_cleaner_agent → telegram_service
```

---

## 6. 📦 ARCHIVOS MAL UBICADOS

### 6.1 Dos directorios `routes/`

```
routes/                    → LEGACY (sync)
  ├── __init__.py
  ├── build_routes.py
  └── notion_routes.py

app/routes/               → MODERNO (async)
  ├── __init__.py
  └── telegram_routes.py
```

**¿Cuál se usa?** `routes/` parece legacy (sync, dependencias en `services/`). `app/routes/` es más moderno pero solo tiene un archivo.

---

### 6.2 Scripts huérfanos en la raíz

```
nexus_notion_tools.py       → debería estar en scripts/ o services/
configure_n8n.py            → debería estar en scripts/
workflow_backup.json        → debería estar en scripts/
verify_setup.py             → debería estar en scripts/
```

---

### 6.3 `scripts/` vacío

El directorio `scripts/` existe pero solo contiene `__init__.py`. Estaba destinado a scripts auxiliares pero nunca se pobló.

---

## 7. ⚠️ OTROS HALLAZGOS

### 7.1 `.gitignore` incompleto

**Faltan:**
```
nexus_state.db              ← SQLite base de datos
chat_states.json            ← Estado persistente JSON
test_*.py                   ← Archivos de prueba (huérfanos)
node_modules/               ← Node.js artifacts
*.db                        ← Cualquier base de datos SQLite
*.db-journal                ← SQLite journals
```

---

### 7.2 `requirements.txt` incompleto

**Actual (6 entradas):**
```
fastapi
uvicorn
python-dotenv
httpx
groq
python-telegram-bot
```

**Faltan dependencias críticas:**
```
notion-client               ← Usado en services/ y routes/
pydantic                    ← Usado en models/schemas.py
google-genai                ← Gemini provider (ai_cascade.py)
openai                      ← OpenRouter / DeepSeek providers
asyncio                     ← No es pip pero asumido
```

---

### 7.3 Test files como ciudadanos de primera clase

Hay **18 archivos `test_*.py`** (desde `test_adaptive_strategy.py` hasta `test_ui.html`) en la raíz del proyecto. Deberían estar en un directorio `tests/`.

---

## 8. 📊 MATRIZ DE DECISIONES

| Ítem | Acción Recomendada | Riesgo | Prioridad |
|------|-------------------|--------|-----------|
| `agents/planner.py` | ELIMINAR | ✅ Seguro | 🔴 Alta |
| `agents/executor.py` | ELIMINAR | ✅ Seguro | 🔴 Alta |
| `agents/blueprint.py` | ELIMINAR | ✅ Seguro | 🔴 Alta |
| `nexus_notion_tools.py` | ELIMINAR | ✅ Seguro | 🔴 Alta |
| `configure_n8n.py` | ELIMINAR (o mover a scripts/) | ✅ Seguro | 🔴 Alta |
| `workflow_backup.json` | ELIMINAR (o mover a scripts/) | ✅ Seguro | 🔴 Alta |
| `package.json` | ELIMINAR | ✅ Seguro | 🔴 Alta |
| `node_modules/` | ELIMINAR (si existe) | ✅ Seguro | 🟡 Media |
| `scripts/` | POBLAR o ELIMINAR | ✅ Seguro | 🟢 Baja |
| `services/notion_service.py` | UNIFICAR con core/notion_gateway.py | ⚠️ Requiere refactor | 🔴 Alta |
| `routes/notion_routes.py` | ELIMINAR (migrar a app/routes/) | ⚠️ Requiere verificación | 🟡 Media |
| `routes/build_routes.py` | ELIMINAR (migrar a app/routes/) | ⚠️ Requiere verificación | 🟡 Media |
| `app/services/telegram_service.py` | REFACTORIZAR (eliminar redundancias) | ⚠️ Requiere cuidado | 🟡 Media |
| `core/state_manager.py` | UNIFICAR con persistence.py | ⚠️ Requiere refactor | 🟡 Media |
| `core/memory_decider.py` | ELIMINAR import/instancia muerta | ✅ Seguro | 🟢 Baja |
| `patterns` type conflict | CORREGIR | ⚠️ Requiere análisis | 🟡 Media |
| `.gitignore` | AMPLIAR | ✅ Seguro | 🟢 Baja |
| `requirements.txt` | COMPLETAR | ✅ Seguro | 🟢 Baja |
| Archivo `c` (raíz) | VERIFICAR y ELIMINAR si es sobrante | ❓ Necesita revisión | 🟢 Baja |
| Test files a `tests/` | MOVER | ✅ Seguro | 🟢 Baja |

---

## 9. 🔗 DIAGRAMA DE DEPENDENCIAS (Simplificado)

```
                     ┌──────────────────────────────────┐
                     │    nexus_bot.py / app/main.py    │
                     │       (Entry Points)             │
                     └──────────┬───────────────────────┘
                                │
                     ┌──────────▼───────────────────────┐
                     │  orchestrators/                  │
                     │  conversation_orchestrator.py    │ ← imports MemoryDecider (muerto)
                     │  cleaning_orchestrator.py        │ ← imports from BOTH worlds
                     └──────────┬───────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
   ┌───────────┐       ┌──────────────┐       ┌──────────────┐
   │  core/    │       │  services/   │       │  app/        │
   │  (async)  │       │  (sync)      │       │  services/   │
   │           │       │              │       │  telegram_   │
   │ notion_   │       │ notion_      │       │  service.py  │
   │ gateway   │       │ service.py   │       │  (god file)  │
   └───────────┘       └──────────────┘       └──────────────┘
                                        DUPLICADO       PUENTE
```

---

## 10. ✅ SUGERENCIA DE PRIORIZACIÓN PARA FASE 3

### Inmediato (Fase 4 — Safe Cleanup):
1. Eliminar `agents/planner.py`, `executor.py`, `blueprint.py`
2. Eliminar `nexus_notion_tools.py`
3. Eliminar `configure_n8n.py`, `workflow_backup.json`
4. Eliminar `package.json` (+ `node_modules/` si existe)
5. Ampliar `.gitignore`
6. Completar `requirements.txt`
7. Eliminar import/instancia muertos de `MemoryDecider`

### Planificado (refactor futuro):
8. Unificar `services/notion_service.py` → `core/notion_gateway.py`
9. Migrar `routes/*` → `app/routes/*` o eliminar
10. Refactorizar `app/services/telegram_service.py`
11. Resolver `patterns` type conflict
12. Mover tests a `tests/` y scripts a `scripts/`

---

*Fin de STRUCTURE_REPORT.md — Listo para Fase 3: CLEANUP_PLAN.md*
