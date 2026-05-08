# 🏗️ ARQUITECTURA NEXUS BNL — AUDITORÍA COMPLETA

> Auditado: 2026-01-05
> Basado exclusivamente en código fuente
> Próxima fase: Sistema Multi-Agente (20 agentes)

---

## TABLA DE CONTENIDOS

1. [System Flow Diagram](#1-system-flow-diagram)
2. [Architecture Breakdown](#2-architecture-breakdown)
3. [Execution Trace](#3-execution-trace)
4. [Subsystem Analysis](#4-subsystem-analysis)
   - 4.1 Decision System
   - 4.2 Action System
   - 4.3 Memory System
   - 4.4 AI Usage
   - 4.5 State Management
5. [Inconsistencies & Risks](#5-inconsistencies--risks)
6. [Readiness for Multi-Agent (Fase 3)](#6-readiness-for-multi-agent-fase-3)
7. [Recommendations](#7-recommendations)

---

## 1. SYSTEM FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────┐
│ TELEGRAM WEBHOOK (nexus_bot.py:58)                                  │
│ POST /webhook → telegram_webhook(request)                           │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TELEGRAM SERVICE (app/services/telegram_service.py:129)              │
│ handle_telegram_update(update)                                       │
│                                                                      │
│  ├─ Guard: "message" in update? ─── NO → return                     │
│  ├─ Guard: user_message exists? ─── NO → return                     │
│  ├─ /aprobar or /rechazar? ─── SI → _handle_approval_command()     │
│  └─ Normal:                                                        │
│       state = get_chat_state(chat_id)    ← JSON file states         │
│       response = await process_message() ← MAIN LOGIC               │
│       await send_telegram_message()      ← response to user         │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ CONVERSATION ORCHESTRATOR (orchestrators/conversation_orchestrator) │
│ process_message(user_message, chat_id, state) → str                 │
│                                                                      │
│  ╔═══════════════════════════════════════════════════════════════╗   │
│  ║ STEP 1: LOAD from SQLite                                      ║   │
│  ║   persisted_identity  = load_persisted_identity(user_id)      ║   │
│  ║   performance_state   = load_persisted_performance(user_id)   ║   │
│  ║   config              = load_persisted_config(user_id)        ║   │
│  ╚═══════════════════════════════════════════════════════════════╝   │
│                              │                                       │
│                              ▼                                       │
│  ╔═══════════════════════════════════════════════════════════════╗   │
│  ║ STEP 2: _process_message_inner()                              ║   │
│  ║   (see Execution Trace below)                                ║   │
│  ╚═══════════════════════════════════════════════════════════════╝   │
│                              │                                       │
│                              ▼                                       │
│  ╔═══════════════════════════════════════════════════════════════╗   │
│  ║ STEP 3: FEEDBACK LOOP                                         ║   │
│  ║   if decision_trace_container:                                ║   │
│  ║     feedback = _detect_feedback(user_message)                 ║   │
│  ║     if feedback is not None:                                  ║   │
│  ║       _run_feedback_loop(trace, feedback, id, perf, cfg)     ║   │
│  ╚═══════════════════════════════════════════════════════════════╝   │
│                              │                                       │
│                              ▼                                       │
│  ╔═══════════════════════════════════════════════════════════════╗   │
│  ║ STEP 4: SAVE to SQLite                                        ║   │
│  ║   _persist_learning_state(user_id, id, perf, cfg)            ║   │
│  ╚═══════════════════════════════════════════════════════════════╝   │
│                              │                                       │
│                              ▼                                       │
│                       return result (str)                            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. ARCHITECTURE BREAKDOWN

### 2.1 Interface Layer
| Component | File | Responsibility |
|-----------|------|---------------|
| Telegram Webhook | `nexus_bot.py:58` | POST /webhook → recibe updates de Telegram |
| Diagnostic Endpoints | `nexus_bot.py:77–328` | /, /set-webhook, /webhook-info, /api-status, /diagnose |
| Telegram Service | `app/services/telegram_service.py:129` | `handle_telegram_update()` — routing de comandos, despacho a orchestrator |
| Telegram Sender | `app/services/telegram_service.py:79` | `send_telegram_message()` — envía respuestas con Markdown |
| Approval Handler | `app/services/telegram_service.py:165` | `_handle_approval_command()` — /aprobar /rechazar |

### 2.2 Cognitive Core
| Component | File | Responsibility |
|-----------|------|---------------|
| Conversation Orchestrator | `orchestrators/conversation_orchestrator.py:448` | `process_message()` — orquesta LOAD→PROCESS→FEEDBACK→SAVE |
| AI Cascade | `core/ai_cascade.py:220` | `call_ai_with_fallback()` — llama 8 APIs en cascada |
| System Prompt | `core/ai_cascade.py:162` | `NEXUS_BNL_SYSTEM_PROMPT` — identidad y reglas del bot |
| Notion Gateway | `core/notion_gateway.py` | CRUD con Notion API (search, fetch, create, update) |
| Backend Client | `core/backend_client.py` | HTTP client para build-app / execute-plan |

### 2.3 Behavior System
| Component | File | Responsibility |
|-----------|------|---------------|
| BehaviorPipeline | `core/behavior_pipeline.py:39` | Orquesta 3 capas deterministas de decisión de comportamiento |
| PatternAwareBehaviorLayer | `core/memory_pattern_aware_behavior_layer.py:40` | Ajusta tone/depth/style por patrones intent/global |
| ConflictResolutionLayer | `core/memory_conflict_resolution_layer.py:36` | Resuelve conflictos entre señales débiles |
| DecisionTraceLayer | `core/memory_decision_trace_layer.py:28` | Captura traza estructurada de decisión |
| AdaptiveBehaviorLayer (legacy) | `core/memory_adaptive_behavior_layer.py:29` | Fallback cuando no hay pipeline — usado en perfil complejo |

### 2.4 Memory System
| Component | File | Responsibility |
|-----------|------|---------------|
| MemoryManager | `core/memory_manager.py:22` | Save/retrieve desde Notion (episodic + semantic) |
| MemoryRouter | `core/memory_router.py:23` | Decide si responder desde RAM vs llamar AI |
| MemorySelector | `core/memory_selector.py:13` | Rankea y selecciona mejor memoria por scoring |
| MemoryDecisionLayer | `core/memory_decision.py:12` | Filtra, re-scorea y selecciona top 5 diversas |
| MemoryCombiner | `core/memory_combiner.py` | Combina múltiples memorias |
| MemorySynthesizer | `core/memory_synthesizer.py` | Sintetiza respuesta desde memorias + identidad |
| MemoryResponseLayer | `core/memory_response_layer.py` | Genera respuesta textual de una memoria individual |
| MemoryDeduplicator | `core/memory_deduplicator.py` | Deduplica por key+value |
| MemoryConflictResolver | `core/memory_conflict_resolver.py` | Resuelve conflictos entre memorias |
| MemoryEvolution | `core/memory_evolution.py` | Evoluciona memorias |
| MemoryInference | `core/memory_inference.py` | Infiere desde memorias |
| MemorySelfCorrectionLayer | `core/memory_self_correction.py` | Auto-corrige memorias |
| MemoryReinforcementLayer | `core/memory_reinforcement.py` | Refuerza memorias |
| MemoryIdentityLayer | `core/memory_identity.py` | Construye identidad desde memorias |
| RAM Cache | `_recent_memory` dict (L108) | Per-chat cache de 10 entradas máximo |

### 2.5 Learning / Feedback System
| Component | File | Responsibility |
|-----------|------|---------------|
| PatternSignalExtractor | `core/memory_pattern_signal_extractor.py:16` | Extrae patrones de mensajes (determinista) |
| PatternIntegrator | `core/memory_pattern_integrator.py:13` | Acumula pesos de patrones en identity |
| ConfidenceFeedbackLayer | `core/memory_confidence_feedback_layer.py:18` | Ajusta pesos por feedback (éxito/fracaso) |
| PerformanceTracker | `core/memory_performance_tracker.py:17` | Contadores de aciertos/fallos por source |
| StabilityGuardLayer | `core/memory_stability_guard_layer.py:18` | Previene ajustes inestables |
| AdaptiveStrategyLayer | `core/memory_adaptive_strategy_layer.py:20` | Ajusta thresholds dinámicamente |

### 2.6 Action System
| Component | File | Responsibility |
|-----------|------|---------------|
| ActionRouter | `core/action_router.py:14` | Mapea intent → clase de acción |
| ApprovalSystem | `core/approval_system.py:29` | Solicita aprobación vía Telegram |
| ActionLogger | `core/action_logger.py:10` | Persiste historial en SQLite |
| BaseAction | `core/actions/base_action.py:7` | ABC para todas las acciones |
| NotionAction | `core/actions/notion_action.py:14` | Ejecuta operaciones Notion |
| FileAction | `core/actions/file_action.py` | (declarado, no verificado) |
| CodeAction | `core/actions/code_action.py` | (declarado, no verificado) |
| CommandAction | `core/actions/command_action.py` | (declarado, no verificado) |

### 2.7 External Integrations
| Integration | File | Protocol |
|-------------|------|----------|
| Notion API | `core/notion_gateway.py` | REST via httpx |
| Backend API | `core/backend_client.py` | HTTP localhost:8000 |
| Telegram API | `app/services/telegram_service.py:79` | REST via httpx |
| 8 AI Providers | `core/ai_cascade.py:97` | Groq, Gemini, DeepSeek, OpenRouter |

### 2.8 Persistence
| Store | Implementation | Data |
|-------|---------------|------|
| SQLite | `core/persistence.py` | identity_patterns, performance_state, adaptive_config, action_history |
| JSON | `core/state_manager.py` | chat_states.json (IDLE, WAITING_CONFIRMATION, etc.) |
| Notion DB | `core/notion_gateway.py` | MEMORY_EPISODES_DB, MEMORY_SEMANTIC_DB, NOTION_DIRTY_DB, NOTION_CLEAN_DB |
| RAM | `_recent_memory` (dict) | Per-chat cache, max 10 entries |

---

## 3. EXECUTION TRACE

### Full trace of `_process_message_inner()` (orchestrators/conversation_orchestrator.py:520)

```
_process_message_inner(user_message, chat_id, state, persisted_*, container)
│
├── [1] DIRECT MEMORY CAPTURE (L548)
│     IF "recuerda" or "remember" in user_message:
│       → Extract key/value
│       → await _memory_manager.save_episode()
│       → Append to _recent_memory[chat_id]
│       → return "🧠 Guardado: {summary}"
│
├── [2] SIMPLE MEMORY FALLBACK (L605)
│     IF chat_id in _recent_memory AND simple_query (como me llamo, que te dije):
│       → _build_memory_response() → if response, return
│
├── [3] MEMORY ROUTER (L615)
│     IF _memory_router.should_use_memory(user_message):
│       IF chat_id in _recent_memory:
│         → _build_memory_response() → if response, return
│       → fallthrough to AI
│
├── [4] COMPLEX PROFILE QUERY (L630)
│     IF chat_id in _recent_memory AND complex_query (que sabes, perfil, sobre mi):
│       → _memory_selector.rank()
│       → MemoryDeduplicator.deduplicate()
│       → MemoryConflictResolver.resolve()
│       → MemoryEvolution.evolve()
│       → MemoryInference.infer()
│       → MemorySelfCorrectionLayer.correct()
│       → MemoryReinforcementLayer.reinforce()
│       → MemoryIdentityLayer.build_identity()
│       → MERGE persisted patterns
│       → MemoryDecisionLayer.decide()
│       → MemoryAdaptiveBehaviorLayer.apply()  ← LEGACY FALLBACK
│       → BehaviorPipeline.run()               ← NEW PIPELINE
│         ├─ MemoryPatternAwareBehaviorLayer.apply()
│         ├─ MemoryConflictResolutionLayer.apply()
│         └─ MemoryDecisionTraceLayer.apply()
│       → Store decision_trace in container
│       → MemorySynthesizer.synthesize()
│       → if synthesized, return
│
├── [5] NOTION CLEANING COMMAND (L704)
│     IF "organiza" or "limpia" in user_message:
│       → Set state NOTION_CLEANING
│       → return response
│
├── [6] WAITING_CONFIRMATION STATE (L710)
│     IF state == WAITING_CONFIRMATION:
│       IF "si/sí/yes/dale": → execute_plan()
│       IF "no/cancelar": → IDLE, cancel
│
├── [7] NOTION CLEANING FLOW (L724)
│     handle_cleaning_flow() → if response, return
│
├── [8] DIRECT COMMANDS (L730)
│     IF "ejecutar ": → execute_plan()
│     IF "plan "/"build "/"crea "/"construye ": → build_app()
│
├── [9] MEMORY RETRIEVAL (L756)
│     memories = await _memory_manager.retrieve(user_message, k=3)
│     memory_context = build_memory_context(memories)
│
├── [10] AI LOOP (L792)— max 5 iterations
│     FOR iteration in range(5):
│       response, api = await call_ai_with_fallback(messages, tools=NOTION_TOOLS)
│       
│       IF no tool_calls:
│         → Extract pattern signals from user message
│         → _pattern_extractor.extract()
│         → _pattern_integrator.integrate()
│         → Detect intent
│         → IF _should_execute_action(intent):
│             → _execute_action()  ← ACTION SYSTEM
│         → BehaviorPipeline.run() (fallback, base behavior)
│         → return content
│       
│       ELSE (has tool_calls):
│         → Execute each tool (notion_search, notion_fetch, etc.)
│         → Append tool result to messages
│         → Next iteration
│
└── return "⚠️ Alcancé el límite de iteraciones."
```

---

## 4. SUBSYSTEM ANALYSIS

### 4.1 DECISION SYSTEM

#### 4.1.1 Intent Detection
- **Dos sistemas de detección de intent coexisten:**

1. **MemoryDecisionLayer._detect_intent()** (`core/memory_decision.py:59`)
   - Usado en ruta de perfil complejo (L661)
   - Detecta: "notion_create", "action", "profile", "general"
   - Basado en keywords deterministas

2. **MemoryDecisionLayer.detect_intent()** (`core/memory_decision.py:85`)
   - Usado en AI Loop (L838)
   - Delega a _detect_intent()
   - IDÉNTICA LÓGICA que el anterior

3. **ActionRouter.INTENT_ACTION_MAP** (`core/action_router.py:22`)
   - 14 intents mapeados: notion_create/update/delete/move, file_read/write/delete/move/copy, code_refactor/lint/format/generate, command_run/sudo/script
   - NO hay código que detecte estos 14 intents desde el mensaje del usuario
   - **BRECHA**: El ActionRouter puede rutear 14 intents, pero el detector de intent solo detecta 4 (notion_create, action, profile, general)

#### 4.1.2 BehaviorPipeline Execution

```
BehaviorPipeline.run(intent, behavior, identity)
│
├── STEP 1: MemoryPatternAwareBehaviorLayer.apply()
│   ├─ Por cada dimensión (tone, depth, style):
│   │   ├─ Extrae patterns[dimension][intent] de identity
│   │   ├─ Valida pesos > 0 y no NaN/Inf
│   │   ├─ Requiere ≥ 2 valores
│   │   ├─ Regla de dominancia: top_weight ≥ second_weight * 1.5
│   │   ├─ Si aplica → source = "intent"
│   │   └─ Skip si la dimensión ya fue modificada
│   │
│   └─ Fallback global (por dimensión sin cambio):
│       ├─ Extrae global_patterns[dimension]
│       ├─ Misma regla de dominancia 1.5x
│       └─ source = "global"
│
├── STEP 2: MemoryConflictResolutionLayer.apply()
│   ├─ Solo para dimensiones SIN cambios
│   ├─ Requiere ≥ 2 valores en intent Y global
│   ├─ Computa hybrid strength (peak + distribution)
│   ├─ Regla de dominancia más suave: 1.3x
│   └─ source = "conflict"
│
└── STEP 3: MemoryDecisionTraceLayer.apply()
    ├─ Compara behavior_before vs behavior_after
    ├─ Determina source global (intent/global/conflict/mixed/none)
    ├─ Computa confidence por dimensión
    └─ Retorna trace completo
```

#### 4.1.3 Decision Trace Structure

```python
decision_trace = {
    "intent": str,         # Intent activo
    "changed": bool,       # ¿Cambió algo?
    "before": dict,        # Behavior antes
    "after": dict,         # Behavior después
    "source": str,         # "intent" | "global" | "conflict" | "mixed" | "none"
    "confidence": float,   # Max confidence across changed dimensions
    "confidence_by_dimension": {
        "tone": float,
        "depth": float,
        "style": float,
    },
    "signals": {
        "intent_strength": float,
        "global_strength": float,
        "combined_used": bool,
    },
    "dimensions": {
        "tone": {
            "source": str,
            "confidence": float,
            "changed": bool,
            "top_score": float,
            "second_score": float,
            "intent_strength": float,
            "global_strength": float,
        },
        # ... depth, style
    },
}
```

#### 4.1.4 Decision Points in the Flow

| Location | Condition | Consequence |
|----------|-----------|-------------|
| L548 | "recuerda" in message | Captura directa de memoria |
| L615 | MemoryRouter.should_use_memory() | Respuesta desde RAM |
| L630 | complex_query + RAM exists | Pipeline completo de perfil |
| L710 | state == WAITING_CONFIRMATION | Aprobación de plan |
| L843 | _should_execute_action(intent) | Ejecución de Action System |
| L806 | AI sin tool_calls | Retorno directo + pattern extraction |

### 4.2 ACTION SYSTEM

#### 4.2.1 How _should_execute_action Works

```python
# conversation_orchestrator.py:234
def _should_execute_action(intent: str) -> bool:
    if not intent:
        return False
    return intent in ActionRouter.INTENT_ACTION_MAP
```

Simplemente verifica si el intent está en el mapa de 14 intents.

**PROBLEMA CRÍTICO**: El detector de intents (`_detect_intent`) solo produce 4 valores:
- "general", "action", "notion_create", "profile"

Los 14 intents en ActionRouter incluyen: "notion_update", "notion_delete", "notion_move", "file_read", "file_write", "file_delete", "file_move", "file_copy", "code_refactor", "code_lint", "code_format", "code_generate", "command_run", "command_sudo", "command_script"

**NINGUNO de estos 14 intents es generado por el detector actual.**

El único intent que coincide es "notion_create" → **parcialmente funcional**.

#### 4.2.2 How intent Maps to ActionRouter

```python
# ActionRouter.route() at action_router.py:42
action_class = INTENT_ACTION_MAP.get(intent)  # Dict lookup
operation = intent.split("_", 1)[1]            # "notion_create" → "create"
action_context = {
    "operation": operation,
    "params": params,
    "decision_trace": decision_trace,
    "user_id": user_id,
}
action_instance = action_class(action_context)
```

#### 4.2.3 How _execute_action Runs

```python
# conversation_orchestrator.py:249
_execute_action(intent, decision_trace, user_message, chat_id):
    1. Route: ActionRouter.route() → BaseAction instance
    2. Approve: if action.requires_approval():
       → ApprovalSystem.request_approval(action, telegram_chat_id)
       → Espera asyncio Future con timeout 300s
       → Usuario responde /aprobar <id> o /rechazar <id>
    3. Execute: await action.execute() → {"success": bool, "result": Any}
    4. Log: ActionLogger.log() → SQLite
    5. Format: _format_action_result() or _format_action_error()
```

#### 4.2.4 Approval Flow

```python
# ApprovalSystem.request_approval() at approval_system.py:51
1. Genera approval_id = uuid4[:8]
2. Crea asyncio.Future → _pending_approvals[approval_id]
3. Envía mensaje Telegram con /aprobar <id> /rechazar <id>
4. await asyncio.wait_for(future, timeout=300)
5. Usuario responde → telegram_service._handle_approval_command()
   → ApprovalSystem.resolve_approval(approval_id, approved)
   → future.set_result(approved)
6. Retorna: True (aprobada), False (rechazada), None (timeout)
```

**PROBLEMA**: `ApprovalSystem.requires_approval()` (L38) usa `action_type.lower()` que es el nombre de clase ("NotionAction"), no la operación. Pero `BaseAction.requires_approval()` en NotionAction (L110) retorna `self.operation == "delete"`. **INCONSISTENCIA**: El ApprovalSystem verifica el tipo de clase, pero la acción verifica la operación. Son dos sistemas de approval diferentes.

#### 4.2.5 Is the Action System Fully Connected or Partially Bypassed?

**PARCIALMENTE CONECTADO**.

Evidencia:

1. ✅ **Ruteo**: ActionRouter está completamente implementado y se llama en `_execute_action()`
2. ✅ **Aprobación**: ApprovalSystem está implementado con Telegram flow
3. ✅ **Logging**: ActionLogger persiste en SQLite
4. ✅ **Ejecución**: NotionAction._create_page() funciona
5. ❌ **Detección de intent**: Solo "notion_create" puede dispararse desde el flujo normal. Los otros 13 intents NUNCA son detectados
6. ❌ **AI Tool Calls bypass**: El AI loop (L906-935) ejecuta herramientas directamente (notion_search, notion_fetch, notion_create) SIN pasar por el Action System
7. ❌ **NotionAction usa notion_create_child_page** (L81) mientras que el AI loop usa `notion_create` (la función directa de gateway) → **DUPLICIDAD**
8. ❌ **FileAction, CodeAction, CommandAction** existen como imports pero NUNCA pueden ser disparados por el detector actual

### 4.3 MEMORY SYSTEM

#### 4.3.1 Memory Retrieval Flow

```
Existen DOS flujos de recuperación de memoria COMPLETAMENTE SEPARADOS:

FLUJO A: RAM Cache (rápido, determinista)
─────────────────────────────────────────
_recent_memory[chat_id] → MemorySelector → MemoryResponseLayer → str
  ↑ 10 entries max       ↑ rank()/select()   ↑ generate()
  ↑ append-only          ↑ scoring v2         ↑ template-based
  
FLUJO B: Notion Retrieval (lento, externo)
────────────────────────────────────────────
_memory_manager.retrieve(query, k=3)
  ├─ _classify_query_type() → "action"/"knowledge"/"contextual"
  ├─ _notion_query_database(DB_ID, query) → raw results
  ├─ _normalize_notion_result() → normalized dicts
  ├─ _score_memory(query, memory) → scoring heurístico
  └─ build_memory_context() → string para prompt AI

FLUJO C: Profile Pipeline (solo desde RAM)
─────────────────────────────────────────────
_recent_memory[chat_id] 
  → MemorySelector.rank()
  → MemoryDeduplicator.deduplicate()
  → MemoryConflictResolver.resolve()
  → MemoryEvolution.evolve()
  → MemoryInference.infer()
  → MemorySelfCorrectionLayer.correct()
  → MemoryReinforcementLayer.reinforce()
  → MemoryIdentityLayer.build_identity()
  → MemoryDecisionLayer.decide()
  → MemoryAdaptiveBehaviorLayer.apply()  (LEGACY)
  → BehaviorPipeline.run()               (NEW)
  → MemorySynthesizer.synthesize()
```

#### 4.3.2 RAM vs Persistent Memory

| Aspecto | RAM (`_recent_memory`) | Notion (via MemoryManager) | SQLite (via persistence) |
|---------|----------------------|---------------------------|-------------------------|
| **Tipo** | Dict in-memory | Notion Database | SQLite tables |
| **Capacidad** | 10 entries/chat | Ilimitado | Ilimitado |
| **Propósito** | Respuesta rápida, perfil | Long-term episodic/semantic | Learning loop state |
| **Persistencia** | Volátil (se pierde al reiniciar) | Persistente | Persistente |
| **Usado para** | Preguntas de memoria simples | Contexto AI | identity patterns, performance, config |
| **Conexión** | Aislado | Sincronizado vía _memory_manager | Módulo persistence |

**PROBLEMA CRÍTICO**: La RAM cache (Flujo A y C) es **independiente** de Notion (Flujo B). Las memorias guardadas en Notion con `_memory_manager.save_episode()` NO se reflejan automáticamente en `_recent_memory`. Viceversa, las memorias en RAM NUNCA se persisten a Notion a menos que el usuario diga "recuerda".

#### 4.3.3 Pattern Extraction & Integration

```
Pattern Extraction (conversation_orchestrator.py:808-833):
─────────────────────────────────────────────────────────
Cuando AI responde SIN tool_calls:
  1. _pattern_extractor.extract({message, intent, behavior})
     → Detecta keywords por dimensión (tone: formal/casual/technical/direct)
     → Retorna lista de pattern_signals
  2. _pattern_integrator.integrate({pattern_signals, identity})
     → Acumula pesos en identity["patterns"][dimension][intent][value]
     → Ej: patterns["tone"]["greeting"]["formal"] += 1.0

Pattern Usage (BehaviorPipeline):
──────────────────────────────────
  1. MemoryPatternAwareBehaviorLayer.apply()
     → Lee patterns[dimension][intent]
     → Si hay dominancia (1.5x), ajusta behavior
  2. Feedback loop ajusta pesos (suma/resta)
```

#### 4.3.4 Feedback Loop Completeness

**¿El aprendizaje afecta realmente el comportamiento?**

**SÍ, PARCIALMENTE**. El loop es:

```
User message → detect_feedback() → ConfidenceFeedbackLayer.apply()
  → Ajusta identity["patterns"] weights
  → PerformanceTracker actualiza contadores
  → StabilityGuard decide si permitir update
  → AdaptiveStrategy ajusta config thresholds
  → _persist_learning_state() → SQLite
  ↓
  (Siguiente mensaje)
  → BehaviorPipeline.run() usa identity["patterns"]
  → Los pesos ajustados afectan tone/depth/style
```

**CICLO COMPLETO**: feedback → pesos → comportamiento → feedback

**PERO**: 
1. Solo mensajes con feedback explícito (positivo/negativo keywords) activan el loop
2. Mensajes neutros (feedback=None) NO activan el loop de performance
3. Pattern extraction SÍ ocurre en mensajes neutros (L808) pero solo en el flujo AI
4. El StabilityGuard requiere MIN_TOTAL=5 y STABLE_TOTAL=10 por source → **el loop NO hace nada hasta tener 10 interacciones con feedback por source**
5. `dominance_threshold` (1.5 en BehaviorPipeline) se compara con 1.3 del ConflictResolutionLayer → **dos constantes diferentes para la misma regla**

#### 4.3.5 Memory Pipeline Completeness

Del análisis del perfil complejo (L639-698):

```
ranked → deduplicate → resolve → evolve → infer → correct → reinforce → build_identity → decide → behavior → synthesize
```

Esta pipeline de 11 pasos solo se ejecuta cuando:
1. Hay RAM cache para el chat
2. El usuario hace una consulta compleja ("qué sabes", "perfil", "sobre mí")

No se ejecuta en el flujo normal de AI.

**PROBLEMA**: `MemoryAdaptiveBehaviorLayer` (legacy) se ejecuta ANTES que `BehaviorPipeline` (L672-680), y luego `BehaviorPipeline.run()` se ejecuta de nuevo. El resultado del pipeline legacy es **sobreescrito** por el nuevo pipeline. Esto es código muerto/no-op desperdiciando CPU.

### 4.4 AI USAGE

#### 4.4.1 All AI Call Sites

| # | Location | File | Responsibility | Determinista? |
|---|----------|------|---------------|---------------|
| 1 | `call_ai_with_fallback()` | `conversation_orchestrator.py:797` | Respuesta principal del bot con tools | ❌ No (language model) |
| 2 | `call_ai_with_fallback()` (merge) | `cleaning_orchestrator.py:84` | Merge análisis + feedback → JSON estructurado | ❌ No |
| 3 | `call_ai_with_fallback()` (duplicate) | `cleaning_orchestrator.py:184` | Merge contenido viejo + nuevo | ❌ No |
| 4 | `call_ai_with_fallback()` (refine) | `cleaning_orchestrator.py:331` | Refinar estructura con feedback | ❌ No |

#### 4.4.2 AI Cascade Configuration

```
8 APIs en orden de prioridad:
1. Groq Llama 3.3 70B (GROQ_API_KEY_1) — max_tokens=2000
2. Groq Llama 3.3 70B (GROQ_API_KEY_2) — backup
3. Gemini 1.5 Flash (GEMINI_API_KEY_1)  — max_tokens=8000
4. Groq Llama 3.1 8B (GROQ_API_KEY_3)   — rápido
5. DeepSeek Chat (DEEPSEEK_API_KEY_1)    — max_tokens=4000
6. Gemini 1.5 Flash (GEMINI_API_KEY_2)   — backup
7. DeepSeek Chat (DEEPSEEK_API_KEY_2)    — backup
8. OpenRouter Llama 3.1 8B (OPENROUTER_API_KEY) — último recurso
```

**PROBLEMAS**:
1. Gemini NO soporta tool_calls en la implementación actual → si se usa Gemini, las tools no funcionan
2. Los modelos tienen diferentes capacidades (Llama 8B vs 70B) → respuestas inconsistentes
3. `current_api_index` es global, NO por usuario → si un usuario quema rate limit, afecta a todos
4. `max_tokens` varía entre 2000 y 8000 → respuestas truncadas si el modelo cambia

### 4.5 STATE MANAGEMENT

#### 4.5.1 Three State Systems

| System | File | Storage | Scope | Persistence |
|--------|------|---------|-------|-------------|
| Chat States | `core/state_manager.py` | `chat_states.json` | Por chat_id | Síncrono, en disco |
| Learning Loop | `core/persistence.py` | SQLite `nexus_state.db` | Por user_id | Transaccional, WAL |
| RAM Cache | `conversation_orchestrator.py:108` | `_recent_memory` dict | Por chat_id | Volátil |

#### 4.5.2 Chat States (state_manager.py)

```python
chat_states: Dict[int, Dict] = {
    chat_id: {
        "state": "IDLE" | "WAITING_CONFIRMATION" | "EXECUTING" | "NOTION_CLEANING",
        "mode": "searching" | "reviewing" | "confirm" | "APPLY" | "saved",
        "plan_id": str | None,
        "pages_pending": list,
        "analysis": dict,
        "cleaning_result": dict,
    }
}
```

**PROBLEMAS**:
- Persistencia en JSON → race conditions si hay concurrencia
- `save_states()` escribe el archivo completo en cada save
- El sistema de memoria multicapa (L49-67) (`memory["short"]`, `memory["medium"]`, `memory["long"]`) NUNCA es usado en el flujo principal. Es **dead code**.

#### 4.5.3 SQLite Schema (persistence.py)

```sql
CREATE TABLE identity_patterns (
    user_id TEXT PRIMARY KEY,
    patterns_json TEXT NOT NULL,
    global_patterns_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE performance_state (
    user_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('intent','global','conflict')),
    correct INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, source)
);

CREATE TABLE adaptive_config (
    user_id TEXT PRIMARY KEY,
    dominance_threshold REAL NOT NULL DEFAULT 1.5,
    intent_weight_factor REAL NOT NULL DEFAULT 0.5,
    global_weight_factor REAL NOT NULL DEFAULT 0.5,
    previous_accuracy_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE action_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT,
    approved INTEGER,
    executed_at TEXT NOT NULL,
    duration_ms INTEGER
);
```

---

## 5. INCONSISTENCIES & RISKS

### 5.1 CRITICAL — Action System Bypass

| Issue | Impact | Evidence |
|-------|--------|----------|
| Detector de intents solo produce 4 valores | 13/14 intents en ActionRouter NUNCA se disparan | `_detect_intent` produce "general"/"action"/"notion_create"/"profile" pero router espera 14 intents |
| AI Loop bypasses Action System | Tool calls (notion_search, notion_fetch, notion_create) se ejecutan DIRECTAMENTE sin routing | `conversation_orchestrator.py:910-935` llama funciones gateway directamente |
| NotionAction duplicado | `NotionAction._create_page()` usa `notion_create_child_page()` mientras el AI loop usa `notion_create()` de gateway | Son funciones diferentes con diferentes parámetros |

### 5.2 CRITICAL — Two Behavior Systems

```
Flujo de perfil complejo (L670-680):
┌─ MemoryAdaptiveBehaviorLayer.apply()  ← LEGACY (v1)
└─ BehaviorPipeline.run()               ← NEW (v2)
```

La salida del legacy es INMEDIATAMENTE sobreescrita por el nuevo pipeline. `_adaptive_fallback.apply()` se ejecuta pero su resultado es descartado después de pasar por el pipeline.

### 5.3 HIGH — Memory Architecture Fragmentation

| Issue | Evidence |
|-------|----------|
| RAM cache no persiste a Notion | `_recent_memory` es append-only, sin persistencia automática |
| Notion memories no llegan a RAM | `_memory_manager.retrieve()` busca en Notion pero no actualiza `_recent_memory` |
| Dos sistemas de scoring | `MemorySelector._score()` (v1) vs `MemoryManager._score_memory()` (v2) |
| Perfil pipeline solo desde RAM | El complejo pipeline de 11 pasos solo funciona si hay datos en `_recent_memory` |

### 5.4 HIGH — Approval System Inconsistencies

```python
# approval_system.py:38 — Revisa action_type (nombre de clase)
def requires_approval(action_type: str) -> bool:
    return action_type.lower() in CRITICAL_ACTIONS

# actions/notion_action.py:110 — Revisa self.operation
def requires_approval(self) -> bool:
    return self.operation == "delete"  # Siempre False para create
```

`_execute_action()` llama `action.requires_approval()` (método de instancia). Pero también hay `ApprovalSystem.requires_approval()` que nunca es llamado desde `_execute_action()`. **El ApprovalSystem tiene un método estático que no se usa en el flujo principal.**

### 5.5 MEDIUM — Dead Code

| File | Dead Code | Evidence |
|------|-----------|----------|
| `state_manager.py:49-73` | Sistema de memoria multicapa | `memory["short"]`, `memory["medium"]`, `memory["long"]` — no referenciado fuera del archivo |
| `state_manager.py:58-63` | `save_short_memory()` | No es llamado en ningún flujo |
| `state_manager.py:66-73` | `clean_memory()` | No es llamado en ningún flujo |
| `memory_adaptive_behavior_layer.py` | Legacy behavior layer | Su output es sobreescrito por BehaviorPipeline |
| `approval_system.py:38-48` | `ApprovalSystem.requires_approval()` | Método estático no usado en flujo principal |

### 5.6 MEDIUM — Config Duplication

| Source | Variables | Location |
|--------|-----------|----------|
| `app/config.py` (via `app/__init__.py?`) | NOTION_TOKEN, API_CONFIG | App layer |
| `core/notion_gateway.py:26-31` | NOTION_TOKEN, NOTION_DIRTY_DB_ID, NOTION_CLEAN_DB_ID | Core layer |
| `core/ai_cascade.py:97-154` | API_CASCADE con API keys | Core layer |
| `core/persistence.py:21` | DB_PATH = core/../nexus_state.db | Core layer |

`NOTION_TOKEN` se carga en dos lugares diferentes (`app/config.py` y `notion_gateway.py`). Si cambia uno pero no el otro, hay inconsistencia.

### 5.7 MEDIUM — Gemini Tool Call Incompatibility

La implementación de Gemini (`ai_cascade.py:295-333`) convierte los mensajes al formato Gemini pero **descarta tool_calls**. Si el modelo Gemini entra por fallback, las tools NO funcionan.

### 5.8 LOW — Dominance Threshold Mismatch

| Layer | Threshold |
|-------|-----------|
| `MemoryPatternAwareBehaviorLayer` (L136) | 1.5 |
| `MemoryConflictResolutionLayer` (L174) | 1.3 |
| `persistence.py` default config | 1.5 |

Si `AdaptiveStrategyLayer` ajusta el threshold vía feedback, el `ConflictResolutionLayer` usa su propia constante 1.3, NO el valor de config. **Feedback loop no afecta ConflictResolutionLayer.**

### 5.9 LOW — Global `current_api_index`

`current_api_index` en `ai_cascade.py:157` es global. Si usuario A quema rate limit en Groq, el índice avanza. Usuario B también recibe el siguiente API aunque Groq esté disponible para B.

---

## 6. READINESS FOR MULTI-AGENT SYSTEM (FASE 3)

### Assessment: **PARTIAL — NO READY WITHOUT MAJOR REFACTORING**

### 6.1 What Would Break

#### AgentRegistry

| Requirement | Status | Why |
|-------------|--------|-----|
| Central agent registry | ❌ NO | No existe mecanismo de registro |
| Agent discovery | ❌ NO | Todo es singleton, sin descubrimiento |
| Agent lifecycle | ❌ NO | Sin create/start/stop/destroy |

**Impact**: No hay infraestructura para registrar 20 agentes.

#### AgentLoader

| Requirement | Status | Why |
|-------------|--------|-----|
| Dynamic module loading | ❌ NO | Todo importado estáticamente |
| Agent isolation | ❌ NO | Singletons globales compartidos |
| Hot-reload | ❌ NO | Sin mecanismo de recarga |

**Impact**: Cada nuevo agente requeriría modificar imports y registros manualmente.

#### AgentCoordinator

| Requirement | Status | Why |
|-------------|--------|-----|
| Inter-agent communication | ⚠️ PARCIAL | El Action System podría adaptarse, pero no hay message bus |
| Task delegation | ⚠️ PARCIAL | Backend client podría delegar, pero no hay routing dinámico |
| Agent state isolation | ❌ NO | `_recent_memory`, `current_api_index` son globales |
| Agent memory isolation | ❌ NO | MemoryManager es singleton, sin namespacing |

### 6.2 What Is Already Compatible

| Component | Compatible | Reason |
|-----------|------------|--------|
| BehaviorPipeline | ✅ SÍ | Determinista, sin side effects, fácil de instanciar por agente |
| ActionRouter | ✅ SÍ | Stateless, mapeo simple intent→acción |
| ApprovalSystem | ✅ SÍ | Stateless, basado en asyncio.Future |
| Persistence | ✅ SÍ | Fail-safe, per-user_id (podría ser per-agent) |
| AI Cascade | ✅ SÍ | Stateless, switchable provider |
| Memory layers | ✅ SÍ | Deterministas, sin estado mutable compartido (excepto RAM cache) |

### 6.3 Critical Blockers

```
1. SINGLETON ARCHITECTURE
   └─ _memory_manager, _behavior_pipeline, _pattern_extractor, etc.
   └→ Imposible tener estado aislado por agente

2. GLOBAL STATE
   └─ current_api_index — afecta a todos los agentes
   └─ _recent_memory — cache global por chat_id
   └─ chat_states — estado de conversación global

3. MONOLITHIC PROCESSING
   └─ _process_message_inner() — 420 líneas, único punto de entrada
   └─ No hay concepto de "agente" — todo es un solo bot

4. TIGHT COUPLING  
   └─ conversation_orchestrator.py importa 30+ módulos directamente
   └─ Cleaning flow importa inline dentro de process_message
```

---

## 7. RECOMMENDATIONS

### 7.1 WHAT SHOULD BE BUILT NEXT (Ordered)

#### Priority 1 — Fix Action System (1-2 days)
- [ ] Extender `_detect_intent()` para soportar los 14 intents del ActionRouter
- [ ] Hacer que el AI loop use el Action System en lugar de llamar funciones gateway directamente
- [ ] Unificar `NotionAction._create_page()` con `notion_create()` de gateway

#### Priority 2 — Merge Memory Systems (2-3 days)
- [ ] Hacer que `_memory_manager.save_episode()` también actualice `_recent_memory`
- [ ] Hacer que `_memory_manager.retrieve()` también cachee resultados en RAM
- [ ] Eliminar `MemoryAdaptiveBehaviorLayer` (legacy) del flujo de perfil complejo
- [ ] Eliminar dead code de `state_manager.py` (memoria multicapa no usada)

#### Priority 3 — Agent Architecture Foundation (3-5 days)
- [ ] Crear `AgentRegistry` — registro central de agentes
- [ ] Crear `BaseAgent` — clase base con ciclo de vida (init/run/cleanup)
- [ ] Convertir singletons en factories o context-managers
- [ ] Reemplazar `current_api_index` global por per-agent API selection

#### Priority 4 — Multi-Agent Communication Bus (2-3 days)
- [ ] Implementar message queue (asyncio.Queue) para comunicación inter-agente
- [ ] Crear `AgentCoordinator` — ruteo de mensajes entre agentes
- [ ] Añadir namespacing a `_recent_memory` y `chat_states` por agente

### 7.2 WHAT SHOULD NOT BE TOUCHED

| Component | Reason |
|-----------|--------|
| BehaviorPipeline | Funciona bien, determinista, bien diseñado |
| DecisionTraceLayer | Estructura sólida, reusable por agentes |
| Persistence (SQLite) | Fail-safe, thread-safe, bien implementado |
| AI Cascade (fallback) | Robusto, aunque necesita per-agent isolation |
| Approval System | Funciona, reusable para multi-agente |
| MemoryDeterministicLayers | Deduplicator, ConflictResolver, Evolution, Inference, etc. — todos sólidos |

### 7.3 WHAT IS FRAGILE

| Component | Fragility | Risk |
|-----------|-----------|------|
| `_recent_memory` (RAM cache) | No persistido, 10 entries, append-only | Pérdida de datos al reiniciar |
| `chat_states.json` | Race condition en concurrencia | Corrupción de estado |
| Gemini tool call incompatibility | No soporta tool_calls | Falla silenciosa en fallback |
| `current_api_index` global | Afecta a todos los usuarios | Inconsistencia entre usuarios |
| Cleaning orchestrator | Import inline dentro de process_message | Acoplamiento fuerte |

### 7.4 WHAT MUST BE REFACTORED BEFORE ADDING AGENTS

#### MUST FIX (Bloqueantes para multi-agente)

1. **Singletons a factories** — `_memory_manager`, `_behavior_pipeline`, `_pattern_extractor`, etc. deben ser instanciables por agente
2. **Global state isolation** — `_recent_memory`, `chat_states`, `current_api_index` deben ser per-agent
3. **Monolithic _process_message_inner** — Refactorizar en módulos más pequeños:
   - `MessageRouter` (decide qué flujo seguir)
   - `ProfilePipeline` (pipeline de 11 pasos)
   - `MemorizationHandler` (captura directa)
   - `AIResponder` (AI loop + pattern extraction)
4. **Action System unification** — Unificar AI tool calls con Action System

#### SHOULD FIX (Alto impacto)

5. **Feedback loop activation** — El StabilityGuard requiere 10+ datos por source. Para testing/multi-agent, debería ser configurable
6. **Dominance threshold sync** — Unificar el threshold entre BehaviorPipeline (1.5) y ConflictResolutionLayer (1.3), o hacer que ConflictResolutionLayer lea de config
7. **Pattern extraction timing** — Actualmente solo se ejecuta en flujo AI sin tool_calls. Debería ejecutarse siempre

#### NICE TO FIX

8. **Eliminar dead code** — MemoryAdaptiveBehaviorLayer, state_manager memory system, ApprovalSystem.requires_approval() estático
9. **Config unificación** — Unificar NOTION_TOKEN en un solo lugar

---

## RESUME EJECUTIVO

```
ESTADO ACTUAL:
├─ Cognitive Core: ✅ COMPLETO
├─ Behavior System: ✅ COMPLETO (con legacy muerto)
├─ Action System: ⚠️ PARCIAL (solo notion_create funciona)
├─ Memory System: ⚠️ FRAGMENTADO (RAM + Notion desconectados)
├─ Learning Loop: ✅ ACTIVO (pero lento, requiere 10+ datos)
├─ Dead Code: ⚠️ 4+ componentes no usados
└─ Multi-Agent Readiness: ❌ NO LISTO

PARA MULTI-AGENTE (Fase 3):
├─ Refactor necesario: 8-12 días estimados
├─ Pasos bloqueantes: 5 (singletons, estado global, monolito)
├─ Componentes reusables: 10+ (pipeline, persistencia, approvals)
└─ Riesgo actual: ALTO — agregar 20 agentes ahora rompería TODO
```
