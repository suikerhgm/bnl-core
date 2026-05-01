# 🧠 Architecture Audit — Nexus BNL

> **Fecha:** 26/04/2026
> **Auditor:** Senior Software Architect (automated analysis)
> **Objetivo:** Detectar problemas estructurales antes de que sean críticos.

---

## 📋 Resumen Ejecutivo

| Métrica | Valor |
|---|---|
| **Líneas totales del proyecto** | ~2500+ |
| **Archivo más grande** | `telegram_service.py` (~1394 líneas) |
| **Responsabilidades en el god file** | 13 |
| **Implementaciones de Notion** | 2 (incompatibles) |
| **Agentes vivos** | 1 (cleaner) |
| **Agentes zombie** | 3 (planner, executor, blueprint) |
| **Risk Level** | 🔴 **CRITICAL** |

---

## 🧠 Architecture Diagnosis

Nexus BNL tiene **2 arquitecturas paralelas conviviendo**:

### Stack Legacy (sync, raíz del proyecto)

| Archivo | Propósito |
|---|---|
| `services/notion_service.py` | Notion SDK sync (síncrono, `notion_client`) |
| `services/build_service.py` | Pipeline de build completo (síncrono) |
| `routes/notion_routes.py` | Endpoints REST /search, /fetch, /create |
| `routes/build_routes.py` | Endpoints /build-app, /execute-plan |

### Stack Moderno (async, dentro de `app/`)

| Archivo | Propósito |
|---|---|
| `app/services/telegram_service.py` | **TODO** — God file |
| `app/services/notion_cleaner_agent.py` | Agente de limpieza IA |
| `app/routes/telegram_routes.py` | Webhook handler (10 líneas — bien) |
| `app/main.py` | FastAPI app (bien) |

El stack moderno es async con `httpx`, el legacy es sync con `notion_client`. **Comparten cero código** para las mismas operaciones de Notion.

---

## ⚠️ Critical Problems

### 🔴 CRITICAL 1: GOD FILE — `telegram_service.py` (~1394 líneas, 13 responsabilidades)

Este archivo hace **todo**:

| # | Responsabilidad | Líneas aprox |
|---|---|---|
| 1 | Load de config + env vars | ~50 |
| 2 | Sistema de memoria multicapa | ~40 |
| 3 | Instanciación del NotionCleanerAgent | ~3 |
| 4 | **Funciones Notion** (search, fetch, create, update, query_database, fuzzy_match) | ~250 |
| 5 | **apply_cleaning_result** (orquestación compleja con AI merging) | ~180 |
| 6 | **Sistema AI Cascade** (AIProvider, AttrDict, 8 providers, 4 clients) | ~300 |
| 7 | Definición de tools (function calling schema) | ~60 |
| 8 | Cliente HTTP del backend (build_app, execute_plan) | ~60 |
| 9 | Formateo de respuestas (_format_plan_result, _format_execution_result) | ~40 |
| 10 | **process_message** (máquina de estados + routing + function calling loop) | ~200 |
| 11 | send_telegram_message (transporte HTTP) | ~60 |
| 12 | handle_telegram_update (entry point webhook) | ~30 |
| 13 | build_notion_blocks (helper de construcción de bloques) | ~40 |

**Problemas:**
- Imposible testear en aislamiento cualquier sub-sistema
- Un solo cambio requiere entender el archivo entero
- Cualquier bug en config rompe todo, no solo un módulo
- El archivo mezcla infraestructura, lógica de negocio, orquestación y transporte

---

### 🔴 CRITICAL 2: Notion duplicado con firmas incompatibles

| Aspecto | `services/notion_service.py` | `telegram_service.py` (embebido) |
|---|---|---|
| Librería | `notion_client` SDK | `httpx` raw API |
| Async/Sync | **Sync** | **Async** |
| `notion_search` | Retorna `List[dict]` (formateado) | Retorna `Dict` (API response crudo) |
| `notion_create` | `(parent_id, title, content)` → page | `(database_id, properties, children)` → database |
| `notion_fetch` | Retorna markdown procesado | Retorna blocks API response |

**Riesgo:**
- Un cambio en Notion API requiere parchear **dos implementaciones distintas**
- Las firmas diferentes garantizan bugs asimétricos (un endpoint funciona, el otro falla)
- La función de la raíz (`services/notion_service.py`) es sync y usa `notion_client.pages.create()` que ya quedó obsoleta por la nueva firma en `telegram_service.py`

---

### 🔴 CRITICAL 3: Dependencia circular latente

```
notion_cleaner_agent.py
  └── importa → call_ai_with_fallback desde telegram_service.py
                    └── telegram_service.py importa → NotionCleanerAgent (instancia global)
```

**Esto significa:**
- No puedes importar `notion_cleaner_agent.py` sin cargar todo `telegram_service.py` (1394 líneas)
- No puedes testear el agente en aislamiento
- No puedes mockear `call_ai_with_fallback` sin mockear medio archivo

**La solución correcta:** `call_ai_with_fallback` debe vivir en `core/ai_cascade.py`, y ambos (`telegram_service.py` y `notion_cleaner_agent.py`) lo importan desde ahí.

---

### 🟡 WARNING 4: State machine embedded en `process_message`

El flujo actual de `process_message()`:

```
process_message()
├── Detectar intención "organiza"/"limpia"
├── WAITING_CONFIRMATION
│   ├── si → call_execute_plan
│   └── no → cancelar
├── NOTION_CLEANING
│   ├── searching → notion_search
│   ├── reviewing → cleaner.analyze_pages()
│   ├── confirm → AI feedback loop o apply_cleaning_result
│   ├── APPLY → (transición interna)
│   └── saved → (estado final)
├── Comandos directos
│   ├── ejecutar {id}
│   └── plan/build/crea {idea} → build_app
└── Flujo normal
    └── AI cascade + function calling loop
```

**Problemas:**
- Cada nuevo flow implica agregar otro if/elif en el mismo bloque
- No se puede reutilizar un flow en otro contexto
- Los estados están acoplados al chat_id vía `state` dict, pero la lógica de cada estado está en el mismo archivo
- La función tiene más de 200 líneas **antes de llegar al flujo normal con IA**

---

### 🟡 WARNING 5: `agents/` zombie

| Archivo | Propósito | ¿Usado? |
|---|---|---|
| `agents/planner.py` | Planificador de tareas | ❌ No |
| `agents/executor.py` | Ejecutor de tareas | ❌ No |
| `agents/blueprint.py` | Constructor de blueprints | ❌ No |
| `app/services/notion_cleaner_agent.py` | Limpiador de Notion | ✅ Sí |

Hay 3 archivos en `agents/` que no son invocados por ningún flujo activo. Crean confusión sobre dónde vive la lógica real de agentes.

---

### 🟡 WARNING 6: Auto-llamado al backend

En `telegram_service.py`:
```python
async def call_build_app(idea: str) -> Dict:
    return await _call_backend("/build-app", {"idea": idea})
```

El bot Telegram **se llama a sí mismo** vía HTTP localhost en vez de invocar directamente a `services/build_service.py`. Esto es un anti-patrón:

- Agrega latencia innecesaria (HTTP loopback)
- Introduce un punto de fallo extra (el servidor FastAPI debe estar corriendo)
- Oculta dependencias: si migras el backend, el bot deja de construir apps
- Duplica lógica de serialización/deserialización

---

## 📊 Risk Level: 🔴 CRITICAL

### ¿Por qué CRITICAL?

1. **El god file hace imposible el testing unitario aislado** — cualquier test requiere importar 1394 líneas con dependencias de red, API keys, y estado global.

2. **La duplicación de Notion garantiza bugs asimétricos** — eventualmente una implementación se actualizará y la otra no, y los endpoints REST darán resultados distintos al bot de Telegram.

3. **No escala a más features** — agregar memoria persistente, ejecución real de código, o multi-agente implica seguir inflando el mismo archivo. Ya está al límite con solo 2 flows.

4. **Dependencia circular impide refactor progresivo** — no puedes extraer el AI cascade sin reescribir imports en ambos lados.

5. **Código zombie desorienta** — 3 archivos en `agents/` que no hacen nada, mientras el agente real vive en `app/services/`.

### Comparativa con el objetivo

| Objetivo | ¿Soportado por estructura actual? |
|---|---|
| Features actuales (2 flows) | ✅ Funciona |
| +1 flow nuevo | ⚠️ Posible pero doloroso |
| +3 flows | ❌ Colapsa |
| Tests unitarios | ❌ Imposible |
| Multi-agente orquestado | ❌ No |
| Escalar a producción | ❌ Frágil |

---

## 🏗️ Recommended Architecture

### Estructura objetivo

```
nexusagentes/
├── app/
│   ├── main.py                    # FastAPI app (keep)
│   ├── config.py                  # Config centralizada (keep)
│   └── routes/
│       ├── notion_routes.py       # Legacy — deprecar
│       ├── build_routes.py        # Legacy — deprecar
│       └── telegram_routes.py     # Thin webhook handler (keep)
│
├── core/                          # 🆕 EXTRACTED from telegram_service.py
│   ├── __init__.py
│   ├── ai_cascade.py              ← call_ai_with_fallback + 4 providers + API_CASCADE
│   ├── notion_gateway.py          ← notion_search|fetch|create|update + query + fuzzy + blocks
│   ├── state_manager.py           ← chat_states, load/save, memory
│   └── models.py                  ← AIProvider, AttrDict, extract_ai_content
│
├── agents/                        # 🆕 CONSOLIDATED
│   ├── __init__.py
│   ├── cleaner_agent.py           ← from app/services/notion_cleaner_agent (migrado aquí)
│   ├── planner.py                 ← (exists, needs integration)
│   └── executor.py                ← (exists, needs integration)
│
├── orchestrators/                 # 🆕 NEW — flows desacoplados
│   ├── __init__.py
│   ├── cleaning_orchestrator.py   ← apply_cleaning_result + build_notion_blocks
│   └── conversation_orchestrator.py ← process_message simplificado (dispatcher)
│
├── services/                      # (legacy — deprecar, no mover)
│   ├── notion_service.py          → deprecado a favor de core/notion_gateway
│   └── build_service.py           → deprecado a favor de agents/planner
│
└── routes/                        # (legacy — deprecar, no mover)
    ├── notion_routes.py           → deprecado a favor de core/notion_gateway
    └── build_routes.py            → deprecado a favor de orchestrators
```

### Lo que se extrae de `telegram_service.py`

| Módulo destino | Contenido | Líneas aprox | Riesgo |
|---|---|---|---|
| `core/state_manager.py` | chat_states, load/save, get_chat_state, memory, save_short_memory, clean_memory | ~60 | 🟢 Mínimo |
| `core/ai_cascade.py` | AIProvider, AttrDict, extract_ai_content, API_CASCADE, call_ai_with_fallback, call_groq, call_gemini, call_deepseek, call_openrouter | ~300 | 🟢 Bajo |
| `core/notion_gateway.py` | NOTION_TOKEN, NOTION_TITLE_PROPERTY, _clean_page_id, notion_search, notion_fetch, notion_create, notion_update, _notion_query_database, _fuzzy_match_title, build_notion_blocks | ~250 | 🟡 Medio |
| `orchestrators/cleaning_orchestrator.py` | apply_cleaning_result, cleaner instance, build_notion_blocks | ~200 | 🟡 Medio |
| `orchestrators/conversation_orchestrator.py` | process_message como dispatcher delegando en sub-orchestrators | ~150 | 🟡 Medio |

### Lo que queda en `telegram_service.py`

| Sección | Líneas aprox |
|---|---|
| Config inicial (imports, env vars, validaciones) | ~80 |
| NOTION_TOOLS (function calling schemas) | ~60 |
| _format_plan_result, _format_execution_result | ~40 |
| process_message simplificado (dispatcher) | ~100 |
| send_telegram_message | ~60 |
| handle_telegram_update | ~30 |
| **Total** | **~370** (vs 1394 actuales) |

---

## 🔄 Refactor Plan (Step-by-step)

### Fase 1: Extracción segura (sin cambiar comportamiento)

**Objetivo:** Reducir `telegram_service.py` en ~600 líneas sin modificar lógica.

#### Paso 1 — Extraer `core/state_manager.py` (🟢 Riesgo mínimo)

```
Mover:
- chat_states
- load_states()
- save_states()
- get_chat_state()
- memory dict
- save_short_memory()
- clean_memory()

Resultado:
- core/state_manager.py: ~60 líneas
- telegram_service.py: -60 líneas
- Dependencias: datetime, json, os, logging (ya disponibles)
```

#### Paso 2 — Extraer `core/ai_cascade.py` (🟢 Riesgo bajo)

```
Mover:
- AIProvider (Enum)
- AttrDict
- extract_ai_content()
- API_CASCADE
- NEXUS_BNL_SYSTEM_PROMPT
- call_ai_with_fallback()
- call_groq()
- call_gemini()
- call_deepseek()
- call_openrouter()
- current_api_index

Resultado:
- core/ai_cascade.py: ~300 líneas
- telegram_service.py: -300 líneas
- Dependencias: httpx, os, logging, ENV vars

⚠️ Nota: NEXUS_BNL_SYSTEM_PROMPT está referenciado en process_message.
    Debe ser re-exportado o importado desde core/ai_cascade.py.
```

#### Paso 3 — Extraer `core/notion_gateway.py` (🟡 Riesgo medio)

```
Mover:
- NOTION_TOKEN, NOTION_CLEAN_DB_ID, NOTION_DIRTY_DB_ID, NOTION_TITLE_PROPERTY
- _clean_page_id()
- notion_search()
- notion_fetch()
- notion_create() (nueva firma)
- notion_update()
- _notion_query_database()
- _fuzzy_match_title()
- build_notion_blocks()

Resultado:
- core/notion_gateway.py: ~250 líneas
- telegram_service.py: -250 líneas

⚠️ Riesgo: notion_create cambió firma recientemente.
    Verificar todos los callers (incluyendo el function calling flow).
```

### Fase 2: Separación de flows

**Objetivo:** Desacoplar la máquina de estados de la lógica de cada flow.

#### Paso 4 — Extraer `orchestrators/cleaning_orchestrator.py` (🟡 Riesgo medio)

```
Mover:
- apply_cleaning_result()
- build_notion_blocks() (si no se movió en Paso 3)
- cleaner instance (NotionCleanerAgent)

Depende de:
- core/ai_cascade.py → call_ai_with_fallback
- core/notion_gateway.py → notion_fetch, notion_create, notion_update, _notion_query_database

Resultado:
- orchestrators/cleaning_orchestrator.py: ~200 líneas
- telegram_service.py: -200 líneas
- notar que cleaner_agent importa de telegram_service — hay que cambiar ese import
```

#### Paso 5 — Migrar `NotionCleanerAgent` a `core/`

```
Cambiar:
  from app.services.telegram_service import call_ai_with_fallback
  → from core.ai_cascade import call_ai_with_fallback

Mover:
  app/services/notion_cleaner_agent.py → agents/cleaner_agent.py

Resultado:
- Se rompe la dependencia circular
- El agente es testeable en aislamiento
- agents/ tiene contenido real
```

#### Paso 6 — Simplificar `process_message` a dispatcher (🟡 Riesgo medio)

```
process_message() se convierte en:
├── Detectar intención (organiza/limpia) → cleaning_orchestrator.start()
├── WAITING_CONFIRMATION → build_orchestrator.confirm()
├── NOTION_CLEANING → cleaning_orchestrator.handle()
│   ├── mode=searching → cleaning.search()
│   ├── mode=reviewing → cleaning.review()
│   ├── mode=confirm → cleaning.confirm_or_refine()
│   ├── mode=APPLY → (transición interna)
│   └── mode=saved → (estado final)
├── Comandos directos → handlers en línea
└── Flujo normal → AI cascade

Resultado:
- process_message: ~100 líneas de dispatcher puro
- Cada flow vive en su orchestrator
- Agregar un flow nuevo = crear orchestrator + agregar 1 línea en dispatcher
```

### Fase 3: Unificación (opcional, más riesgoso)

**Objetivo:** Eliminar la duplicación de Notion.

#### Paso 7 — Migrar `services/notion_service.py` → `core/notion_gateway.py`

```
services/notion_service.py (sync, SDK)
  → Reescribir routes/notion_routes.py para usar core/notion_gateway (async)

⚠️ Esto cambia la API pública REST:
  - notion_search retorna Dict ahora, no List[dict]
  - notion_create requiere properties+children, no (parent_id, title, content)
  - notion_fetch retorna blocks raw, no markdown
  - Los endpoints pueden necesitar adaptación en los clientes (n8n, etc.)
```

#### Paso 8 — Eliminar auto-llamado al backend

```
call_build_app() ya no llama a POST /build-app
En su lugar: usa agents/planner.plan_project() directamente

Resultado:
- Menos latencia (sin HTTP loopback)
- Un punto menos de fallo
- Dependencias explícitas
```

### Fase 4: Limpieza

**Objetivo:** Eliminar código zombie y documentar legacy.

#### Paso 9 — Deprecar `services/` y `routes/` raíz

```
Acciones:
1. Agregar docstring "⚠️ DEPRECATED — migrar a core/" en cada archivo
2. No eliminar hasta verificar que ningún caller externo (n8n) los use
3. Actualizar README para indicar la nueva estructura
```

#### Paso 10 — Limpiar `agents/`

```
Acciones:
1. Si planner.py, executor.py, blueprint.py no se usan:
   - Mover a agents/_archive/ o documentar como "no integrados aún"
2. Si se van a integrar:
   - Migrar imports a core/ai_cascade.py
   - Crear orchestrator correspondiente
```

---

## Resumen de impacto

```
╔══════════════════════════════════╗
║     ANTES DEL REFACTOR           ║
╠══════════════════════════════════╣
║ telegram_service.py: 1394 líneas ║
║ 13 responsabilidades             ║
║ 2 implementaciones de Notion     ║
║ Dependencia circular             ║
║ Sin tests posibles               ║
║ Código zombie                    ║
╚══════════════════════════════════╝

              ↓
       9-10 pasos
              ↓

╔══════════════════════════════════╗
║     DESPUÉS DEL REFACTOR         ║
╠══════════════════════════════════╣
║ telegram_service.py: ~350 líneas ║
║ 3 responsabilidades              ║
║ 1 implementación de Notion       ║
║ Sin dependencias circulares      ║
║ Tests aislados posibles          ║
║ Sin código zombie                ║
║ Cada módulo testeable            ║
╚══════════════════════════════════╝
```

---

## Prioridades recomendadas

| Prioridad | Paso | Esfuerzo | Impacto | Riesgo |
|---|---|---|---|---|
| 🔴 1 | Extraer `core/state_manager.py` | 15 min | -60 líneas | 🟢 Mínimo |
| 🔴 2 | Extraer `core/ai_cascade.py` | 30 min | -300 líneas | 🟢 Bajo |
| 🔴 3 | Extraer `core/notion_gateway.py` | 30 min | -250 líneas | 🟡 Medio |
| 🟡 4 | Migrar cleaner_agent a `core/` | 10 min | Rompe dependencia circular | 🟢 Bajo |
| 🟡 5 | Extraer cleaning_orchestrator | 20 min | Desacopla flow completo | 🟡 Medio |
| 🟡 6 | Simplificar process_message | 30 min | Arquitectura escalable | 🟡 Medio |
| 🟢 7 | Unificar Notion (opcional) | 1-2h | Sin duplicación | 🔴 Alto |
| 🟢 8 | Limpiar zombies | 15 min | Claridad | 🟢 Bajo |

---

*Reporte generado por análisis automatizado de arquitectura.*
