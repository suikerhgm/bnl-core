# 🗺️ SYSTEM AUDIT — NexusAgentes

> **Date:** 29/04/2026
> **Type:** Full system architecture mapping (READ-ONLY audit)
> **Status:** COMPLETE — Phase 1 of 5

---

## 1. SYSTEM OVERVIEW

NexusAgentes (Nexus BNL v3.0) es una **agencia autónoma de desarrollo IA** que funciona como un **bot de Telegram** con capacidades de memoria, comportamiento adaptativo, aprendizaje por refuerzo, y orquestación multi-IA.

### Main Subsystems

| Subsistema | Descripción | Archivos clave |
|---|---|---|
| **AI Cascade** | Fallback multi-proveedor con 8 APIs en cascada (Groq×3, Gemini×2, DeepSeek×2, OpenRouter) | `core/ai_cascade.py` |
| **Behavior Pipeline** | Pipeline determinista que ajusta tono/profundidad/estilo según patrones acumulados | `core/behavior_pipeline.py`, `core/memory_pattern_aware_behavior_layer.py`, etc. |
| **Memory System** | Memoria episódica en Notion + RAM cache + recuperación/ranking/síntesis | `core/memory_manager.py`, `core/memory_router.py`, etc. |
| **Feedback Loop** | Ajuste de pesos de patrones basado en feedback del usuario | `core/memory_confidence_feedback_layer.py`, `core/memory_performance_tracker.py` |
| **Learning Loop** | Ciclo completo: decisión → traza → feedback → actualización → rendimiento → estrategia → estabilidad | `orchestrators/conversation_orchestrator.py` |
| **Notion Integration** | Gateway HTTP async para CRUD de Notion | `core/notion_gateway.py` |
| **App Building** | Pipeline de generación y ejecución de proyectos vía backend local | `core/backend_client.py`, `agents/`, `routes/` |
| **Cleaning Flow** | Limpieza y estructuración de conocimiento de Notion vía IA | `orchestrators/cleaning_orchestrator.py` |

### Architecture Coexistence

El sistema tiene **dos arquitecturas coexistiendo**:

- **Stack moderno (activo):** `core/` → `orchestrators/` → `app/` — async, httpx, determinista
- **Stack legacy (en desuso parcial):** `services/`, `routes/` raíz — sync, depends obsoletas

---

## 2. CORE PIPELINES

### 2.1 Behavior Pipeline (Determinista, Sin IA)

```
BehaviorPipeline.run(intent, behavior, identity)
  │
  ├─ STEP 1: MemoryPatternAwareBehaviorLayer
  │     Ajusta tone/depth/style usando patrones específicos de intención
  │     Fallback: global_patterns si no hay dominancia en intent
  │     Regla: 1.5× dominancia relativa, requiere ≥2 valores
  │
  ├─ STEP 2: MemoryConflictResolutionLayer
  │     Resuelve señales débiles combinando intent + global con peso adaptativo
  │     Regla: dominancia 1.3×, ponderación por distribución dinámica
  │
  └─ STEP 3: MemoryDecisionTraceLayer
        Captura traza estructurada (source, confidence, signal strengths)
        Retorna decision_trace + behavior final
```

### 2.2 Memory Retrieval & Synthesis Pipeline

```
MemoryRouter.should_use_memory() → bool
  → MemoryManager.retrieve() → list (Notion DB query)
  → MemorySelector.rank() → scored list
  → MemoryCombiner.combine() → str response
  ── O pipeline completo ──
  → MemoryDeduplicator → MemoryConflictResolver → MemoryEvolution
  → MemoryInference → MemorySelfCorrectionLayer → MemoryReinforcementLayer
  → MemoryIdentityLayer.build_identity() → identity dict
  → MemoryDecisionLayer.decide() → filtered top N
  → MemoryAdaptiveBehaviorLayer.apply() → behavior dict
  → MemorySynthesizer.synthesize() → final response str
```

### 2.3 Conversation Flow

```
process_message(user_message, chat_id, state)
  │
  ├─ STEP 1: LOAD — carga identidad, rendimiento y config desde SQLite
  ├─ STEP 2: PROCESS (interno)
  │     ├─ 2a. Direct Memory Capture ("recuerda"/"remember")
  │     ├─ 2b. Simple Memory Fallback (preguntas predefinidas)
  │     ├─ 2c. Memory Router (reglas de enrutamiento)
  │     ├─ 2d. Complex Profile Queries (pipeline completo)
  │     ├─ 2e. Notion Cleaning Flow (state machine)
  │     ├─ 2f. Direct Commands ("ejecutar", "build", "plan")
  │     └─ 2g. AI Loop (normal flow con function calling)
  ├─ STEP 3: FEEDBACK — aplica feedback loop si hubo decisión
  └─ STEP 4: SAVE — persiste estado del learning loop
```

---

## 3. COMPONENT INVENTORY

### 3.1 Core Infrastructure

| Componente | Propósito | Inputs | Outputs | Dependencias |
|---|---|---|---|---|
| `ai_cascade.py` | Fallback multi-IA con 8 providers | messages, tools (opcional) | response dict + index | httpx, dotenv |
| `notion_gateway.py` | Gateway HTTP async para Notion API | query/page_id/properties | dict con resultado | httpx, os |
| `persistence.py` | Persistencia SQLite del learning loop | user_id, identity/performance/config | datos cargados/guardados | sqlite3 (stdlib) |
| `state_manager.py` | Estado de chat en JSON (legacy) | chat_id, message | estado guardado/cargado | json (stdlib) |
| `backend_client.py` | Cliente HTTP para backend local | idea/plan_id | resultado de build/execute | httpx |
| `logging.py` | Config centralizada de logging | name | logger configurado | logging (stdlib) |
| `formatters.py` | Formateo de respuestas para Telegram | result dicts | strings formateados | Ninguna |
| `tools.py` | Schemas de function calling para IA | N/A | lista de dicts OpenAI-compatible | Ninguna |

### 3.2 Behavior Decision Layer (core/)

| Componente | Propósito | Dependencias |
|---|---|---|
| `MemoryPatternAwareBehaviorLayer` | Ajusta tone/depth/style según patrones de identidad | Ninguna (pura) |
| `MemoryConflictResolutionLayer` | Resuelve conflictos entre señales débiles intent vs global | Ninguna (pura) |
| `MemoryDecisionTraceLayer` | Captura traza estructurada de la decisión | Ninguna (pura) |
| `MemoryConfidenceFeedbackLayer` | Ajusta pesos de patrones según feedback | Ninguna (pura) |
| `MemoryPerformanceTracker` | Trackea tasas de éxito por fuente de decisión | Ninguna (pura) |
| `MemoryStabilityGuardLayer` | Previene ajustes inestables de estrategia | Ninguna (pura) |
| `MemoryAdaptiveStrategyLayer` | Ajusta thresholds según rendimiento | Ninguna (pura) |
| `MemoryPatternIntegrator` | Acumula señales de patrón en identity | Ninguna (pura) |
| `MemoryPatternDecayLayer` | Decaimiento controlado de pesos de patrones | Ninguna (pura) |
| `MemoryGlobalPatternLayer` | Agrega patrones a través de todos los intents | Ninguna (pura) |
| `BehaviorPipeline` | Orquesta pipeline completo | Los 3 layers superiores |

### 3.3 Memory Retrieval (core/)

| Componente | Propósito | Dependencias |
|---|---|---|
| `MemoryRouter` | Decide si responder desde memoria vs AI | Ninguna (rule-based) |
| `MemoryDecider` | Decide si almacenar interacción como memoria | Ninguna (rule-based) |
| `MemoryManager` | Guarda/recupera de Notion DBs | `notion_gateway.py` |
| `MemorySelector` | Rankea y selecciona mejor memoria para query | Ninguna (rule-based) |
| `MemoryCombiner` | Combina múltiples memorias en texto natural | `MemoryResponseLayer` |
| `MemoryDeduplicator` | Elimina valores duplicados | Ninguna |
| `MemoryConflictResolver` | Mantiene mejor score por key | Ninguna |
| `MemoryEvolution` | Marca duplicados como "deprecated" | Ninguna |
| `MemoryInference` | Infiere contexto del goal del usuario | Ninguna (hardcoded) |
| `MemorySelfCorrectionLayer` | Corrige conflictos en almacenamiento persistente | `MemoryManager` |
| `MemoryReinforcementLayer` | Refuerza memorias repetidas | `MemoryManager` |
| `MemoryIdentityLayer` | Construye perfil de identidad del usuario | Ninguna |
| `MemoryDecisionLayer` | Filtra y re-scorea memorias | Ninguna |
| `MemoryAdaptiveBehaviorLayer` | Determina tone/depth/style/verbosity | Ninguna (rule-based) |
| `MemorySynthesizer` | Convierte memorias+identidad+behavior en respuesta final | `MemoryResponseLayer` |
| `MemoryResponseLayer` | Convierte memoria estructurada a lenguaje natural | Ninguna (templates) |

### 3.4 Orchestrators

| Componente | Propósito | Dependencias |
|---|---|---|
| `conversation_orchestrator.py` | Orquesta flujo completo de conversación | 25+ módulos de core/ |
| `cleaning_orchestrator.py` | State machine de limpieza de Notion | `notion_gateway`, `ai_cascade`, `NotionCleanerAgent` |

### 3.5 Agents

| Componente | Propósito | Estado |
|---|---|---|
| `agents/planner.py` | Placeholder — optimiza plan de tareas | **ZOMBIE** — no hace nada real |
| `agents/executor.py` | Placeholder — ejecuta tareas | **ZOMBIE** — retorna "pending_execution" |
| `agents/blueprint.py` | Placeholder — enriquece blueprint | **ZOMBIE** — retorna mismo dict |

### 3.6 App Layer

| Componente | Propósito | Dependencias |
|---|---|---|
| `app/main.py` | Bot runner con PTB polling | `orchestrators.conversation_orchestrator` |
| `nexus_bot.py` | Servidor FastAPI webhook | `app.services.telegram_service` (legacy) |
| `app/config.py` | Config de la app | dotenv |
| `app/dependencies.py` | Dependency injection | FastAPI |
| `services/build_service.py` | Servicio de build de apps | FastAPI |
| `services/notion_service.py` | Servicio Notion (sync) | notion-client SDK |
| `routes/build_routes.py` | Rutas de build | FastAPI |
| `routes/notion_routes.py` | Rutas de Notion | FastAPI |

---

## 4. DATA FLOW

### 4.1 Identity

```
Estructura dual:
  identity["patterns"][dimension][intent][value] = float  (del MemoryPatternIntegrator)
  identity["global_patterns"][dimension][value] = float   (del MemoryGlobalPatternLayer)
  
Además del MemoryIdentityLayer:
  identity["user_name"] = str | None
  identity["project_name"] = str | None
  identity["goals"] = [str]
  identity["interests"] = [str]
  identity["patterns"] = [str]  (lista simple de patrones detectados)

Flujo:
  1. MemoryIdentityLayer.build_identity() → identity simple desde ranked_memories
  2. MemoryPatternIntegrator → identity["patterns"][dim][intent][val] += weight
  3. MemoryPatternDecayLayer → identity["patterns"] *= 0.995, prune < 0.05
  4. MemoryGlobalPatternLayer → identity["global_patterns"] agregado
  5. MemoryConfidenceFeedbackLayer → ajusta identity["patterns"] según feedback
  6. persistencia: load_identity() / save_identity() en SQLite
```

### 4.2 Behavior

```
Estructura:
  behavior = {
    "tone": "casual" | "technical" | "direct",
    "depth": "short" | "medium" | "deep",
    "style": "structured" | "narrative" | "concise",
    "verbosity": int (1-5)
  }

Flujo:
  1. MemoryAdaptiveBehaviorLayer.apply() → behavior base (rule-based)
  2. MemoryPatternAwareBehaviorLayer.apply() → ajustado por patrones
  3. MemoryConflictResolutionLayer.apply() → resuelto si señales débiles
  4. MemoryDecisionTraceLayer.apply() → captura before/after
  5. MemorySynthesizer.synthesize() → consume behavior final
```

### 4.3 Decision Trace

```
Estructura:
  decision_trace = {
    "intent": str,
    "changed": bool,
    "before": {...behavior antes},
    "after": {...behavior después},
    "source": "intent" | "global" | "conflict" | "mixed" | "none",
    "confidence": float (top/second ratio),
    "confidence_by_dimension": {"tone": float, "depth": float, "style": float},
    "signals": {"intent_strength": float, "global_strength": float, "combined_used": bool},
    "dimensions": { por dimensión: source, confidence, changed, scores, strengths }
  }

Flujo:
  1. Creado por MemoryDecisionTraceLayer al final del BehaviorPipeline
  2. Consumido por MemoryConfidenceFeedbackLayer (ajuste de patrones)
  3. Consumido por MemoryPerformanceTracker (trackeo de éxito)
```

### 4.4 Performance State

```
Estructura:
  performance_state = {
    "intent":  {"correct": int, "total": int},
    "global":  {"correct": int, "total": int},
    "conflict": {"correct": int, "total": int}
  }

Flujo:
  1. MemoryPerformanceTracker.apply() → actualiza contadores
  2. MemoryStabilityGuardLayer.apply() → decide si permite update
  3. MemoryAdaptiveStrategyLayer.apply() → ajusta config si guard permite
  4. persisted via save_performance()/load_performance() en SQLite
```

### 4.5 Config

```
Estructura:
  config = {
    "dominance_threshold": float (1.1–2.0, default 1.5),
    "intent_weight_factor": float (0.1–1.0, default 0.5),
    "global_weight_factor": float (0.1–1.0, default 0.5),
    "previous_accuracy": dict (opcional)
  }

Flujo:
  1. MemoryAdaptiveStrategyLayer.apply() → ajusta según rendimiento
  2. MemoryConflictResolutionLayer consume dominance_threshold
  3. Guardado vía save_config()/load_config() en SQLite
```

---

## 5. LEARNING LOOP

El learning loop completo sigue esta secuencia:

```
DECISIÓN
  BehaviorPipeline.run(intent, behavior, identity)
  Retorna: final_behavior + decision_trace
  ↓
TRAZA
  decision_trace captura qué cambió, por qué, y con qué confianza
  ↓
FEEDBACK
  MemoryConfidenceFeedbackLayer.apply(decision_trace, feedback, identity)
  - feedback=True  → +0.2(intent), +0.15(conflict), +0.1(global)
  - feedback=False → -0.2(intent), -0.15(conflict), -0.1(global)
  - Escalado por confianza: scale = min(1.0, confidence/2.0)
  - Soft cap: MAX_WEIGHT = 10.0
  ↓
PERFORMANCE TRACKING
  MemoryPerformanceTracker.apply(decision_trace, feedback, state)
  - Incrementa total/correct por fuente
  ↓
STABILITY GUARD
  MemoryStabilityGuardLayer.apply(performance_state, config)
  - MIN_TOTAL=5, STABLE_TOTAL=10, MIN_DELTA=0.05
  - Retorna allow_update bool
  ↓
STRATEGY UPDATE (si guard permite)
  MemoryAdaptiveStrategyLayer.apply(performance_state, config)
  - intent > 0.7 → +0.1 weight
  - global < 0.5 → -0.1 weight  
  - conflict > 0.8 → -0.1 threshold
  - Todos clamped a rangos definidos
```

**Estado actual:** El loop está implementado en `process_message()` pero el feedback se basa en detección de palabras clave de corrección. No hay feedback automático desde respuestas AI.

---

## 6. PERSISTENCE LAYER

### 6.1 SQLite (`core/persistence.py`)

| Tabla | Propósito | Usado por |
|---|---|---|
| `identity_patterns` | Patrones de identidad por usuario | `orchestrators/conversation_orchestrator.py` |
| `performance_state` | Métricas de rendimiento por fuente | `orchestrators/conversation_orchestrator.py` |
| `adaptive_config` | Configuración adaptativa por usuario | `orchestrators/conversation_orchestrator.py` |

### 6.2 JSON File (`core/state_manager.py`)

| Archivo | Propósito | Usado por |
|---|---|---|
| `chat_states.json` | Estados de conversación por chat_id | `orchestrators/conversation_orchestrator.py`, `cleaning_orchestrator.py` |

### 6.3 RAM (Volátil)

| Estructura | Propósito | Problema |
|---|---|---|
| `_recent_memory` (dict) | Caché de memoria reciente en RAM | Se pierde al reiniciar |
| `user_states` (dict en `app/main.py`) | Estados de usuario en polling mode | Se pierde al reiniciar |

### 6.4 Notion (Remoto)

| Database | Propósito |
|---|---|
| `NOTION_MEMORY_EPISODES_DB_ID` | Memoria episódica |
| `NOTION_MEMORY_SEMANTIC_DB_ID` | Memoria semántica |
| `NOTION_DIRTY_DB_ID` | Conocimiento no procesado |
| `NOTION_CLEAN_DB_ID` | Conocimiento estructurado/limpio |

### 6.5 Gaps Identificados

- **No hay migraciones**: SQLite tablas se crean con `CREATE IF NOT EXISTS` — sin schema versioning
- **RAM-only user_states**: Se pierde todo estado de conversación al reiniciar
- **No hay backup/export**: No hay mecanismo para exportar datos SQLite
- **No hay logging persistence**: Solo stdout, sin archivos rotativos

---

## 7. EXTERNAL INTEGRATIONS

### 7.1 Notion

| Operación | Endpoint API | Async | Autenticación |
|---|---|---|---|
| `notion_search` | POST /v1/search | Sí (httpx) | Token Bearer |
| `notion_fetch` | GET /v1/pages/{id} + GET /v1/blocks/{id}/children | Sí | Token Bearer |
| `notion_create` | POST /v1/pages | Sí | Token Bearer |
| `notion_update` | PATCH /v1/pages/{id} | Sí | Token Bearer |
| `_notion_query_database` | POST /v1/databases/{id}/query | Sí | Token Bearer |

**Dual implementation problem:** `routes/notion_routes.py` y `services/notion_service.py` usan SDK sync de notion-client, mientras `core/notion_gateway.py` usa httpx async. Son incompatibles.

### 7.2 Telegram

| Operación | Endpoint | Protocolo |
|---|---|---|
| Webhook receive | POST /webhook | FastAPI endpoint |
| setWebhook | POST bot{token}/setWebhook | httpx |
| getWebhookInfo | GET bot{token}/getWebhookInfo | httpx |
| Polling mode (alternativo) | getUpdates | python-telegram-bot |

**Dual implementation:** `nexus_bot.py` usa webhook, `app/main.py` usa polling.

### 7.3 AI APIs (8 Providers)

| Provider | URL | Modelo |
|---|---|---|
| Groq 1-3 | api.groq.com/openai/v1 | llama-3.3-70b / llama-3.1-8b |
| Gemini 1-2 | generativelanguage.googleapis.com | gemini-1.5-flash |
| DeepSeek 1-2 | api.deepseek.com/v1 | deepseek-chat |
| OpenRouter | openrouter.ai/api/v1 | llama-3.1-8b-instruct:free |

### 7.4 Backend Local

| Operación | Endpoint | Propósito |
|---|---|---|
| `call_build_app` | POST /build-app | Genera plan de proyecto |
| `call_execute_plan` | POST /execute-plan | Ejecuta tareas del plan |

---

## 8. CURRENT RISKS / LIMITATIONS

### 8.1 Architecture Risks

| Riesgo | Descripción | Severidad |
|---|---|---|
| **Dual Notion implementations** | `core/notion_gateway.py` (async httpx) y `services/notion_service.py` (sync SDK) son incompatibles. Bugs asimétricos garantizados. | **ALTA** |
| **God file legacy** | `app/services/telegram_service.py` (~1394 líneas, 13 responsabilidades) sigue siendo importado por `nexus_bot.py`. Contiene lógica que ahora está duplicada en `orchestrators/`. | **ALTA** |
| **Dual entry points** | `nexus_bot.py` (FastAPI webhook) y `app/main.py` (PTB polling) — dos formas de iniciar el bot, lógica duplicada. | **MEDIA** |
| **Global mutable state** | `current_api_index` (índice global de API) y `chat_states` (dict global) no son thread-safe. Sin locks. | **MEDIA** |
| **Circular dependency** | `cleaning_orchestrator.py` → `NotionCleanerAgent` → `telegram_service.py` (que a su vez importa del cleaning). | **MEDIA** |

### 8.2 Code Quality Risks

| Riesgo | Descripción | Severidad |
|---|---|---|
| **Zombie agents** | `agents/planner.py`, `executor.py`, `blueprint.py` son placeholders que no hacen nada. | **BAJA** |
| **Dead code paths** | `routes/notion_routes.py` y `routes/build_routes.py` probablemente no se usan desde que el stack moderno tomó control. | **MEDIA** |
| **Zombie files** | `nexus_notion_tools.py`, `configure_n8n.py`, `workflow_backup.json` son legacy no referenciado. | **BAJA** |
| **Import interno redundante** | `MemoryAdaptiveBehaviorLayer` importado inline dentro de `conversation_orchestrator.py` (línea 411) en vez de al inicio. | **BAJA** |
| **Router y routes duplicados** | `app/routes/` y raíz `routes/` coexisten — confuso y probablemente solo uno está activo. | **MEDIA** |

### 8.3 Persistence Risks

| Riesgo | Descripción | Severidad |
|---|---|---|
| **RAM-only user states** | `user_states` en `app/main.py` no persistido — reinicio del servidor pierde conversaciones en curso. | **ALTA** |
| **No schema versioning** | SQLite sin migraciones — cambios de schema requieren borrar DB manual. | **MEDIA** |
| **chat_states.json sin lock** | Archivo JSON compartido sin protección de concurrencia. | **MEDIA** |

### 8.4 Production Readiness

| Riesgo | Descripción | Severidad |
|---|---|---|
| **No auth en endpoints** | Cualquiera puede POST a /webhook, /set-webhook sin validación. | **ALTA** |
| **No rate limiting** | Sin protección contra abuso. | **MEDIA** |
| **No logging persistence** | Logs solo stdout, sin archivos, sin rotación. | **MEDIA** |
| **No unit tests for pipeline** | Todos los tests son integración. Los layers del pipeline no tienen tests unitarios. | **MEDIA** |
| **Feedback loop no automático** | El learning loop requiere feedback manual basado en keywords. No hay feedback automático. | **MEDIA** |

### 8.5 Naming & Structure Issues

| Riesgo | Descripción | Severidad |
|---|---|---|
| **Dual `patterns` key** | `MemoryIdentityLayer` usa `patterns` como `List[str]`, mientras `MemoryPatternIntegrator` usa `patterns` como `Dict[str, Dict]`. Conflicto de tipo en la misma key. | **ALTO** |
| **MemoryDecider no usado** | `MemoryDecider` está importado en `conversation_orchestrator.py` pero `decide()` nunca se llama. | **BAJA** |
| **Naming inconsistente** | Mezcla de inglés y español en nombres de variables, comments, y docstrings. | **BAJA** |

---

## 9. FILE INVENTORY SUMMARY

| Directorio | Archivos | Estado |
|---|---|---|
| `core/` | 30 archivos | ✅ Activo — stack moderno |
| `orchestrators/` | 2 archivos | ✅ Activo — orquestación |
| `app/` | 5+ archivos | ⚠️ Parcialmente activo |
| `agents/` | 3 archivos | 🧟 Zombies (placeholders) |
| `routes/` (raíz) | 2 archivos | 🧟 Probablemente legacy |
| `services/` (raíz) | 2 archivos | 🧟 Legacy (sync SDK) |
| `scripts/` | 1 archivo | Vacío |
| `models/` | 1 archivo | Schemas de datos |
| Raíz | 25+ archivos | Mixto (tests, docs, configs) |

---

*End of Phase 1 — SYSTEM AUDIT complete.*
*Next: Phase 2 — STRUCTURE REPORT*
