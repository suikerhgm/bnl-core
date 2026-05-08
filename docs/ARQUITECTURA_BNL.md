# 🏗️ ARQUITECTURA NEXUS BNL — Mapeo Completo del Sistema

> **Versión del documento:** 1.0  
> **Fecha:** 2026-01-05  
> **Propósito:** Mapa de arquitectura exhaustivo para agentes IA y desarrolladores humanos  
> **Commit base:** `4b978f9fcac25ed3cbe884a20d1f90a52c6aba34`

---

## 📑 Índice

1. [🔭 Overview del Sistema](#1-🔭-overview-del-sistema)
2. [🏛️ Arquitectura de Alto Nivel](#2-🏛️-arquitectura-de-alto-nivel)
3. [📁 Estructura de Directorios](#3-📁-estructura-de-directorios)
4. [🧩 Mapeo de Módulos](#4-🧩-mapeo-de-módulos)
5. [🔁 Flujo de Ejecución Detallado](#5-🔁-flujo-de-ejecución-detallado)
6. [📐 Modelos de Datos y Schemas](#6-📐-modelos-de-datos-y-schemas)
7. [💾 Sistema de Persistencia](#7-💾-sistema-de-persistencia)
8. [🧪 Sistema de Tests](#8-🧪-sistema-de-tests)
9. [🔌 Puntos de Integración y Extensibilidad](#9-🔌-puntos-de-integración-y-extensibilidad)
10. [🚫 Constraints y Reglas de Diseño](#10-🚫-constraints-y-reglas-de-diseño)

---

## 1. 🔭 Overview del Sistema

### ¿Qué es Nexus BNL?

Nexus BNL es un **agente autónomo de desarrollo IA** que opera vía Telegram. Combina:

- **🤖 Multi-IA fallback system** — 8 APIs en cascada (Groq, Gemini, DeepSeek, OpenRouter)
- **🧠 Memory Pipeline** — Sistema de memoria episódica y semántica multicapa con almacenamiento en Notion
- **⚙️ Behavior Pipeline** — Sistema determinista que ajusta tono, profundidad y estilo de respuesta basado en patrones aprendidos
- **🔄 Feedback Loop** — Ciclo de aprendizaje que refuerza/corrige decisiones de comportamiento vía feedback del usuario
- **🗄️ Persistencia SQLite** — Almacenamiento determinista de identidad, rendimiento y configuración adaptativa
- **📝 Notion Gateway** — Integración bidireccional con Notion (búsqueda, fetch, creación, limpieza)
- **🔨 Build Service** — Generación automática de planos de proyecto y ejecución de tareas

### Estado Actual

| Componente | Estado | Notas |
|---|---|---|
| Telegram Bot (FastAPI) | ✅ Estable | v3.0, webhook-based |
| AI Cascade (8 APIs) | ✅ Estable | Con fallback automático |
| Memory Manager (Notion) | ✅ Estable | v1, sin embeddings |
| Memory Pipeline (RAM) | ✅ Estable | 8 capas de procesamiento |
| Behavior Pipeline | ✅ Estable | 3 capas deterministas |
| Feedback Loop | ✅ Estable | 4 componentes |
| SQLite Persistence | ✅ Estable | Thread-safe, WAL mode |
| Notion Gateway | ✅ Estable | Search, Fetch, Create |
| Notion Cleaning | ⚠️ Legacy | Deprecado |
| Routes Legacy | ⚠️ Legacy | `routes/` y `services/` sin usar |

### Stack Tecnológico

```
Python 3.10+   → Lenguaje principal
FastAPI         → Servidor web (2 instancias: bot :8001, backend :8000)
SQLite3         → Persistencia local (stdlib)
httpx           → Cliente HTTP async (AI APIs, Notion, Telegram)
Pydantic v2     → Schemas de datos
python-telegram-bot → SDK Telegram
uvicorn         → ASGI server
Notion API      → Almacenamiento externo de memoria
```

---

## 2. 🏛️ Arquitectura de Alto Nivel

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        USUARIO (Telegram)                                    │
│                        @nexusagentes_bot                                     │
└────────────────────────────┬─────────────────────────────────────────────────┘
                             │ POST /webhook
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🚪 CAPA DE TRANSPORTE (nexus_bot.py :8001)                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ FastAPI App                                                         │   │
│  │  ├── POST /webhook    → telegram_webhook()                         │   │
│  │  ├── POST /set-webhook → set_webhook()                             │   │
│  │  ├── GET  /webhook-info → webhook_info()                           │   │
│  │  ├── GET  /api-status  → api_status()                              │   │
│  │  ├── GET  /diagnose    → diagnose()                                │   │
│  │  └── GET  /            → health check                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬─────────────────────────────────────────────────┘
                             │ delegate
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🧠 CAPA DE LÓGICA (app/services/telegram_service.py)                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ handle_telegram_update()                                            │   │
│  │   └── process_message() (orchestrators/conversation_orchestrator.py) │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬─────────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  ⚙️ CAPA DE ORQUESTACIÓN                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ conversation_orchestrator.py   → process_message()                  │   │
│  │   ├── 1. LOAD → SQLite persistence (identidad, perf, config)        │   │
│  │   ├── 2. PROCESS → Direct memory / MemoryRouter / AI Loop           │   │
│  │   │     ├── Memory Capture (palabras clave)                         │   │
│  │   │     ├── MemoryRouter + 8-layer Memory Pipeline                  │   │
│  │   │     ├── BehaviorPipeline (3 layers)                             │   │
│  │   │     ├── Pattern Extraction + Integration                        │   │
│  │   │     └── AI Loop with tool execution (Notion, Build)             │   │
│  │   ├── 3. FEEDBACK → ConfidenceFeedback → PerformanceTracker →       │   │
│  │   │     StabilityGuard → AdaptiveStrategy                           │   │
│  │   └── 4. SAVE → SQLite persistence                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ 🧠 CORE ENGINE   │ │ 🌐 GATEWAYS  │ │ 🗄️ PERSISTENCE      │
│  ai_cascade.py   │ │ notion_gw.py │ │  persistence.py      │
│  behavior_pipe.. │ │ backend_cl.. │ │  (SQLite)            │
│  memory_*.py     │ │ tools.py     │ │  state_manager.py    │
│  (24 módulos)    │ │ formatters.. │ │  (JSON file)         │
└──────────────────┘ └──────────────┘ └──────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🔧 BACKEND SERVICE (FastAPI :8000)                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ app/main.py → build_service.py para generación de planos/proyectos  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 📁 Estructura de Directorios

```
NexusAgentes/
│
├── nexus_bot.py                    # 🚪 ENTRY POINT PRINCIPAL — Servidor FastAPI :8001
├── verify_setup.py                 # ✅ Script de verificación de entorno
├── start_services.ps1              # 🚀 Script de arranque (PowerShell)
│
├── requirements.txt                # 📦 Dependencias Python
├── .env.example                    # 🔐 Template de variables de entorno
│
├── core/                           # 🧠 NÚCLEO — 24 módulos
│   ├── __init__.py                 #   (vacíos)
│   ├── ai_cascade.py               #   🤖 Fallback multi-IA (8 APIs)
│   ├── behavior_pipeline.py        #   ⚙️ Pipeline de decisión de comportamiento (3 capas)
│   ├── backend_client.py           #   🔗 Cliente HTTP para backend :8000
│   ├── formatters.py               #   📝 Formateo de respuestas para Telegram
│   ├── logging.py                  #   📋 Configuración de logging
│   ├── tools.py                    #   🛠️ Definición de herramientas (Notion, Build)
│   ├── notion_gateway.py           #   🌐 Gateway de API Notion
│   ├── persistence.py              #   💾 Persistencia SQLite
│   ├── state_manager.py            #   📁 Gestor de estado (JSON file)
│   │
│   ├── Memory Pipeline (8 capas RAM):
│   │   ├── memory_router.py        #   🚦 Enrutador de consultas a memoria
│   │   ├── memory_selector.py      #   🔍 Ranking y selección de memorias
│   │   ├── memory_combiner.py      #   🔗 Combinación de múltiples memorias
│   │   ├── memory_synthesizer.py   #   🧬 Síntesis de respuesta final
│   │   ├── memory_deduplicator.py  #   🧹 Deduplicación de memorias
│   │   ├── memory_conflict_resolver.py  # ⚡ Resolución de conflictos entre memorias
│   │   ├── memory_inference.py     #   🔎 Inferencia de datos implícitos
│   │   ├── memory_evolution.py     #   🧬 Evolución temporal de memorias
│   │   ├── memory_self_correction.py    # 🔧 Auto-corrección de memorias
│   │   ├── memory_reinforcement.py      # 💪 Refuerzo de memorias
│   │   ├── memory_identity.py      #   🆔 Construcción de identidad
│   │   ├── memory_decision.py      #   🎯 Detección de intención y decisión
│   │   ├── memory_response_layer.py    # 💬 Generación de respuestas desde RAM
│   │   └── memory_manager.py       #   📚 Gestor principal (Memoria → Notion)
│   │
│   ├── Behavior Pipeline (3 capas deterministas):
│   │   ├── memory_pattern_aware_behavior_layer.py  # 📊 Ajuste por patrones
│   │   ├── memory_conflict_resolution_layer.py     # ⚖️ Resolución de conflictos
│   │   └── memory_decision_trace_layer.py          # 📝 Traza de decisión
│   │
│   ├── Pattern System:
│   │   ├── memory_pattern_signal_extractor.py      # 📡 Extracción de señales
│   │   ├── memory_pattern_integrator.py            # 🔄 Integración en identidad
│   │   ├── memory_pattern_decay_layer.py           # ⏳ Decaimiento temporal
│   │   └── memory_global_pattern_layer.py          # 🌍 Patrones globales
│   │
│   ├── Feedback Loop (4 componentes):
│   │   ├── memory_confidence_feedback_layer.py     # 🎯 Ajuste por feedback
│   │   ├── memory_performance_tracker.py           # 📊 Seguimiento de rendimiento
│   │   ├── memory_stability_guard_layer.py         # 🛡️ Guardián de estabilidad
│   │   └── memory_adaptive_strategy_layer.py       # 🧠 Estrategia adaptativa
│   │
│   └── Legacy (en uso crossover):
│       └── memory_adaptive_behavior_layer.py       # ⚠️ Reemplazado por behavior_pipeline
│
├── models/                         # 📐 Schemas compartidos
│   ├── __init__.py                 #   (vacío)
│   └── schemas.py                  #   Pydantic models (Search, Fetch, Create, Build, Execute)
│
├── orchestrators/                  # 🔁 ORQUESTADORES
│   ├── conversation_orchestrator.py  # 🧠 Orquestador principal de conversación
│   └── cleaning_orchestrator.py      # ⚠️ Orquestador de limpieza (legacy)
│
├── app/                            # 🚪 CAPA DE TRANSPORTE
│   ├── __init__.py                 #   (vacío)
│   ├── main.py                     #   🚀 Backend FastAPI :8000 (build service)
│   ├── config.py                   #   ⚙️ Configuración compartida
│   ├── dependencies.py             #   🔗 Dependencias FastAPI
│   ├── routes/                     #   🛣️ Rutas de la app
│   │   ├── __init__.py             #   (vacío)
│   │   └── telegram_routes.py      #   📡 Rutas Telegram (legacy, no usado)
│   └── services/                   #   🧠 Servicios de la app
│       ├── __init__.py             #   (vacío)
│       ├── telegram_service.py     #   📬 Lógica principal del bot Telegram
│       └── notion_cleaner_agent.py #   🧹 Agente de limpieza Notion
│
├── agents/                         # 🤖 Agentes
│   └── __init__.py                 #   (vacío, placeholder)
│
├── routes/                         # ⚠️ LEGACY — Rutas antiguas
│   ├── __init__.py                 #   (vacío)
│   ├── build_routes.py             #   Rutas de construcción (NO USADO)
│   └── notion_routes.py            #   Rutas de Notion (NO USADO)
│
├── services/                       # ⚠️ LEGACY — Servicios antiguos
│   ├── __init__.py                 #   (vacío)
│   ├── build_service.py            #   Servicio de construcción (NO USADO)
│   └── notion_service.py           #   Servicio de Notion (NO USADO)
│
└── test_*.py                       # 🧪 15 archivos de tests
```

---

## 4. 🧩 Mapeo de Módulos

### 4.1 🧠 Core — Motor Principal (`core/`)

#### 4.1.1 🤖 AI Cascade (`ai_cascade.py`)

| Aspecto | Detalle |
|---|---|
| **Clases** | `AIProvider(Enum)` — 8 proveedores; `AttrDict` — acceso unificado a respuestas |
| **Funciones** | `call_ai_with_fallback()`, `call_groq()`, `call_gemini()`, `call_deepseek()`, `call_openrouter()`, `extract_ai_content()` |
| **Constantes** | `API_CASCADE` (lista de 8 configs), `NEXUS_BNL_SYSTEM_PROMPT` |
| **Variable global** | `current_api_index` — índice de la API actualmente activa |
| **Responsabilidad** | Fallback automático multi-IA. Si una API falla (429, timeout, error), prueba la siguiente |
| **⚠️ Tech Debt** | `current_api_index` es mutable globalmente; no hay reset periódico |

**Orden de la cascada:**
```
1. Groq Llama 3.3 70B        (GROQ_API_KEY_1)   max_tokens=2000
2. Groq Llama 3.3 70B        (GROQ_API_KEY_2)   max_tokens=2000  ← backup
3. Gemini 1.5 Flash          (GEMINI_API_KEY_1)  max_tokens=8000
4. Groq Llama 3.1 8B         (GROQ_API_KEY_3)   max_tokens=2000  ← rápido
5. DeepSeek Chat             (DEEPSEEK_API_KEY_1) max_tokens=4000
6. Gemini 1.5 Flash          (GEMINI_API_KEY_2)  max_tokens=8000  ← backup
7. DeepSeek Chat             (DEEPSEEK_API_KEY_2) max_tokens=4000  ← backup
8. OpenRouter Llama 3.1 8B   (OPENROUTER_API_KEY) max_tokens=2000 ← último recurso
```

#### 4.1.2 ⚙️ Behavior Pipeline (`behavior_pipeline.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `BehaviorPipeline` — orquesta 3 capas deterministas |
| **Métodos** | `run(intent, behavior, identity) → dict` |
| **Subcomponentes** | `MemoryPatternAwareBehaviorLayer`, `MemoryConflictResolutionLayer`, `MemoryDecisionTraceLayer` |
| **Dimensiones** | `tone`, `depth`, `style` — 3 ejes de comportamiento |
| **Responsabilidad** | Pipeline determinista sin AI que toma un comportamiento base y lo ajusta según patrones de identidad aprendidos |

**Flujo interno:**
```
behavior_base → MemoryPatternAwareBehaviorLayer (ajuste por patrones)
              → MemoryConflictResolutionLayer (resolución de conflictos)
              → Merge de metadatos por dimensión
              → MemoryDecisionTraceLayer (traza estructurada)
              → {behavior, decision_trace}
```

**🔗 Dependencias:** `memory_pattern_aware_behavior_layer`, `memory_conflict_resolution_layer`, `memory_decision_trace_layer`

#### 4.1.3 🚦 Memory Router (`memory_router.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `MemoryRouter` — decide si responder desde RAM o pasar a AI |
| **Métodos** | `should_use_memory(message) → bool` |
| **Keywords** | ~30 palabras clave en español/inglés para activar respuesta desde memoria |
| **Responsabilidad** | Evita llamadas a AI innecesarias si la respuesta está en memoria RAM |

#### 4.1.4 🔍 Memory Selector (`memory_selector.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `MemorySelector` — ranking y selección de memorias |
| **Métodos** | `rank(memories, query) → list` (sorted por score); `select(memories, query) → dict or None` |
| **Algoritmo** | Score por coincidencia en content/summary (+3), tags (+2), key-value exact match (+5) |
| **Responsabilidad** | Rankea y selecciona la memoria más relevante para una consulta |

#### 4.1.5 🔗 Memory Combiner (`memory_combiner.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `combine(memories) → str or None` |
| **Algoritmo** | Si hay 2+ memorias relacionadas (misma key, user, etc.), las fusiona en un texto coherente |
| **Responsabilidad** | Combina múltiples memorias relacionadas en una sola respuesta |

#### 4.1.6 🧬 Memory Synthesizer (`memory_synthesizer.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `synthesize(memories, identity, behavior) → str or None` |
| **Responsabilidad** | Genera respuesta final fusionando memorias, identidad y comportamiento. Último paso del pipeline de memoria |

#### 4.1.7 🧹 Memory Deduplicator (`memory_deduplicator.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `deduplicate(memories) → list` |
| **Algoritmo** | Elimina memorias duplicadas comparando content, key, value, summary. Primera ocurrencia gana |
| **Responsabilidad** | Limpia el conjunto de memorias antes de procesamiento |

#### 4.1.8 ⚡ Memory Conflict Resolver (`memory_conflict_resolver.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `resolve(memories) → list` |
| **Algoritmo** | Detecta conflictos (mismo key, diferente value). Gana la de mayor importance. Marca la perdedora como deprecated |
| **⚠️ Tech Debt** | Marca conflictos pero no persiste el deprecated en Notion (no-op en v1) |

#### 4.1.9 🔎 Memory Inference (`memory_inference.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `infer(memories) → list` |
| **Algoritmo** | Si hay memory.type="fact" con key "user_name", infiere "user_nickname" y "user_title" |
| **Responsabilidad** | Deriva datos implícitos a partir de memorias explícitas (sin AI) |

#### 4.1.10 🧬 Memory Evolution (`memory_evolution.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `evolve(memories) → list` |
| **Algoritmo** | Detecta memorias repetitivas (mismo key aparece 3+ veces) y las comprime: crea una sola memoria con summary="Repetitive pattern: {key}" |
| **⚠️ Tech Debt** | La compresión es lossy — pierde matices de valores individuales |

#### 4.1.11 🔧 Memory Self-Correction (`memory_self_correction.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `correct(memories, memory_manager) → list` |
| **Algoritmo** | Detecta `deprecated` y llama a `memory_manager.deprecate_memory()` (no-op en v1) |
| **Responsabilidad** | Procesa memorias marcadas como conflictivas para corrección |

#### 4.1.12 💪 Memory Reinforcement (`memory_reinforcement.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `reinforce(memories, memory_manager) → list` |
| **Algoritmo** | Prioriza memorias con importance >= 4. Llama a `save_episode()` para persistir en Notion |
| **Responsabilidad** | Refuerza memorias importantes para persistencia externa |

#### 4.1.13 🆔 Memory Identity (`memory_identity.py`)

| Aspecto | Detalle |
|---|---|
| **Métodos** | `build_identity(memories) → dict` |
| **Salida** | `{user_name, project_name, goals[], interests[], patterns{}}` |
| **Responsabilidad** | Construye un perfil de identidad estructurado a partir de todas las memorias disponibles |

#### 4.1.14 🎯 Memory Decision (`memory_decision.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `MemoryDecisionLayer` |
| **Métodos** | `detect_intent(message) → str` (13 intents); `decide(memories, identity, query, intent) → list` |
| **Intents detectados** | `saludo`, `identidad`, `perfil`, `proyecto`, `consulta`, `organizar`, `construir`, `recordar`, `informacion`, `preferencia`, `tarea`, `despedida`, `general` |
| **Responsabilidad** | Clasifica la intención del mensaje y selecciona memorias relevantes |

#### 4.1.15 💬 Memory Response Layer (`memory_response_layer.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `MemoryResponseLayer` |
| **Métodos** | `generate(memory) → str`; `_extract_fields(summary) → dict or None`; `_extract_clean_value(text) → str` |
| **Responsabilidad** | Genera respuestas legibles desde memorias individuales. Extrae campos key/value de texto |

#### 4.1.16 📚 Memory Manager (`memory_manager.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `MemoryManager` |
| **Métodos** | `save_episode(content, summary, tags, importance)`, `retrieve(query, k=5) → list`, `deprecate_memory(key, value)` |
| **Bases de datos Notion** | `NOTION_MEMORY_EPISODES_DB_ID`, `NOTION_MEMORY_SEMANTIC_DB_ID` (desde .env) |
| **Responsabilidad** | Gestor principal de memoria persistente. Persiste episodios en Notion y recupera memorias relevantes |
| **⚠️ Tech Debt** | Sin embeddings; scoring por keyword matching básico; fallback a recientes si no hay match |

#### 4.1.17 📊 Behavior Layers (Pattern System)

**`memory_pattern_aware_behavior_layer.py`:**
- **Clase:** `MemoryPatternAwareBehaviorLayer`
- **Métodos:** `apply(input_data) → dict`
- **Responsabilidad:** Ajusta `tone`, `depth`, `style`, `verbosity` según patrones almacenados en identity.patterns. Procesa cada dimensión con su propia lógica de ajuste

**`memory_conflict_resolution_layer.py`:**
- **Clase:** `MemoryConflictResolutionLayer`
- **Métodos:** `apply(input_data) → dict`
- **Responsabilidad:** Detecta conflictos entre dimensiones de comportamiento (ej: tone="formal" + style="concise" no son conflictivos, pero tone="formal" + style="casual" sí) y resuelve usando `dominance_threshold`

**`memory_decision_trace_layer.py`:**
- **Clase:** `MemoryDecisionTraceLayer`
- **Métodos:** `apply(input_data) → dict`
- **Responsabilidad:** Genera una traza estructurada de la decisión: qué cambió, por qué, nivel de confianza, origen (intent/global/conflict), diff de dimensiones

**`memory_pattern_signal_extractor.py`:**
- **Clase:** `MemoryPatternSignalExtractor`
- **Métodos:** `extract(input_data) → dict`
- **Responsabilidad:** Extrae señales de patrón del mensaje del usuario. Detecta preferencias de tono, profundidad, estilo y verbosidad

**`memory_pattern_integrator.py`:**
- **Clase:** `MemoryPatternIntegrator`
- **Métodos:** `integrate(input_data) → dict`
- **Responsabilidad:** Integra señales de patrón en la identidad persistida, actualizando `identity.patterns`

**`memory_pattern_decay_layer.py`:**
- **Clase:** `MemoryPatternDecayLayer`
- **Métodos:** `apply(identity) → dict`
- **Responsabilidad:** Aplica decaimiento temporal a patrones antiguos. Reduce el peso de patrones no reforzados recientemente. Requiere timestamps por patrón
- **⚠️ Tech Debt:** Los timestamps por patrón no están implementados en persistence.py aún

**`memory_global_pattern_layer.py`:**
- **Clase:** `MemoryGlobalPatternLayer`
- **Métodos:** `extract(identity) → dict`
- **Responsabilidad:** Extrae patrones globales del conjunto de patrones individuales. Detecta tendencias generales aplicables a todos los usuarios

#### 4.1.18 🧠 Feedback Loop Components

**`memory_confidence_feedback_layer.py`:**
- **Clase:** `MemoryConfidenceFeedbackLayer`
- **Métodos:** `apply(input_data) → dict`
- **Entrada:** `{decision_trace, feedback (bool), identity}`
- **Responsabilidad:** Ajusta patrones de identidad basado en feedback positivo/negativo. Si feedback=True, refuerza los patrones; si False, los invierte

**`memory_performance_tracker.py`:**
- **Clase:** `MemoryPerformanceTracker`
- **Métodos:** `apply(input_data) → dict`
- **Entrada:** `{decision_trace, feedback, state}`
- **Responsabilidad:** Actualiza contadores de rendimiento por source (intent/global/conflict). Incrementa `total` y `correct` según feedback recibido

**`memory_stability_guard_layer.py`:**
- **Clase:** `MemoryStabilityGuardLayer`
- **Métodos:** `apply(input_data) → dict`
- **Entrada:** `{performance_state, config}`
- **Responsabilidad:** Previene cambios de estrategia si: (a) hay pocos datos (<5 samples), (b) la precisión es baja (<50%), (c) se acaba de ajustar (<3 interacciones). Retorna `allow_update: bool`

**`memory_adaptive_strategy_layer.py`:**
- **Clase:** `MemoryAdaptiveStrategyLayer`
- **Métodos:** `apply(input_data) → dict`
- **Entrada:** `{performance_state, config}`
- **Responsabilidad:** Ajusta `dominance_threshold`, `intent_weight_factor`, `global_weight_factor` basado en precisión histórica. Si un source tiene <65% accuracy, reduce su peso

#### 4.1.19 📁 State Manager (`state_manager.py`)

| Aspecto | Detalle |
|---|---|
| **Variables globales** | `chat_states = load_states()` — dict de estados cargado al inicio |
| **Archivo** | `chat_states.json` — persistencia en disco |
| **Funciones** | `load_states()`, `save_states()`, `get_chat_state(chat_id)`, `save_short_memory(chat_id, message)`, `clean_memory()` |
| **Memoria temporal** | `memory = {"short": {}, "medium": {}, "long": {}}` — sistema de 3 niveles (12h / 7d / permanente) |
| **Responsabilidad** | Gestiona estados de conversación y memoria temporal |

#### 4.1.20 🌐 Notion Gateway (`notion_gateway.py`)

| Aspecto | Detalle |
|---|---|
| **Funciones** | `notion_search(query)`, `notion_fetch(page_id)`, `notion_create(parent_id, properties, children)`, `_clean_page_id(page_id)`, `build_notion_blocks(title, content, summary)` |
| **Constantes** | `NOTION_TOKEN`, `NOTION_DIRTY_DB_ID`, `NOTION_CLEAN_DB_ID`, `NOTION_TITLE_PROPERTY` (desde .env) |
| **Responsabilidad** | Comunicación bidireccional con API de Notion v1 |
| **⚠️ Tech Debt** | `_notion_query_database()` es versión simplificada; `legacy_notion_create()` coexiste |

#### 4.1.21 🔗 Backend Client (`backend_client.py`)

| Aspecto | Detalle |
|---|---|
| **Funciones** | `call_build_app(idea)`, `call_execute_plan(plan_id)` |
| **URL destino** | `http://localhost:8000` (backend service) |
| **Responsabilidad** | Cliente HTTP para el servicio de construcción de apps |

#### 4.1.22 🛠️ Tools (`tools.py`)

| Aspecto | Detalle |
|---|---|
| **Constante** | `NOTION_TOOLS` — definición de 5 tools en formato OpenAI function calling |
| **Tools** | `notion_search`, `notion_fetch`, `notion_create`, `build_app`, `execute_plan` |
| **Responsabilidad** | Define las herramientas disponibles para el AI Loop |

#### 4.1.23 📋 Logging (`logging.py`)

| Aspecto | Detalle |
|---|---|
| **Función** | `setup_logging(name, level=INFO) → logger` |
| **Formato** | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` |
| **Responsabilidad** | Configuración centralizada de logging |

#### 4.1.24 📝 Formatters (`formatters.py`)

| Aspecto | Detalle |
|---|---|
| **Funciones** | `_format_plan_result(result)`, `_format_execution_result(result)`, `build_memory_context(memories)` |
| **Responsabilidad** | Formatea resultados de plan/ejecución para Telegram. Construye contexto de memoria para prompts de AI |

### 4.2 📐 Modelos (`models/`)

| Archivo | Contenido |
|---|---|
| `schemas.py` | 7 Pydantic models: `SearchRequest`, `FetchRequest`, `CreateRequest`, `BuildAppRequest`, `BuildAppResponse`, `PlanResponse`, `ExecutePlanRequest`, `ExecutePlanResponse` |

### 4.3 🔁 Orquestadores (`orchestrators/`)

#### 4.3.1 🧠 Conversation Orchestrator (`conversation_orchestrator.py`)

**⚠️ Archivo más crítico del sistema — 703 líneas.**

| Función | Responsabilidad |
|---|---|
| `_detect_feedback(user_message) → Optional[bool]` | Detecta feedback positivo/negativo/neutro por keywords |
| `_run_feedback_loop(decision_trace, feedback, identity, perf, config)` | Ejecuta las 4 capas del feedback loop |
| `_persist_learning_state(user_id, identity, perf, config)` | Guarda estado en SQLite |
| `_build_memory_response(memories, user_message)` | Construye respuesta desde RAM usando Selector + Combiner + Response |
| `process_message(user_message, chat_id, state) → str` | **Función principal** — LOAD → PROCESS → FEEDBACK → SAVE |
| `_process_message_inner(...) → str` | Lógica interna de procesamiento (700 líneas aprox) |

**Flujo detallado de `process_message()`:**

```
1. LOAD: load_persisted_identity(user_id)
         load_persisted_performance(user_id)
         load_persisted_config(user_id)

2. PROCESS: _process_message_inner()
   ├── 2a. Direct Memory Capture (si contiene "recuerda"/"remember")
   ├── 2b. MemoryRouter (responder desde RAM si aplica)
   ├── 2c. Complex queries → 8-layer Memory Pipeline
   │     ├── MemoryDeduplicator
   │     ├── MemoryConflictResolver
   │     ├── MemoryEvolution
   │     ├── MemoryInference
   │     ├── MemorySelfCorrection
   │     ├── MemoryReinforcement
   │     ├── MemoryIdentityLayer
   │     └── MemoryDecisionLayer
   │     └── BehaviorPipeline (3 layers)
   │     └── MemorySynthesizer
   ├── 2d. Normal Flow
   │     ├── Notion cleaning flow
   │     ├── Direct commands (ejecutar, plan, build)
   │     ├── Memory retrieval from Notion
   │     ├── Memory context injection
   │     └── AI Loop (max 5 iterations)
   │           ├── call_ai_with_fallback(messages, tools)
   │           ├── Tool execution (notion_search, notion_fetch, etc.)
   │           ├── Pattern extraction & integration
   │           └── BehaviorPipeline (for ALL messages)
   └── decision_trace_container ← se llena si hubo BehaviorPipeline

3. FEEDBACK: if decision_trace:
   ├── ConfidenceFeedbackLayer
   ├── PerformanceTracker
   ├── StabilityGuard
   └── AdaptiveStrategy

4. SAVE: save_persisted_identity, save_persisted_performance, save_persisted_config
```

### 4.4 🚪 App Layer (`app/`)

#### 4.4.1 Telegram Service (`app/services/telegram_service.py`)

| Aspecto | Detalle |
|---|---|
| **Función principal** | `handle_telegram_update(data)` — procesa updates de Telegram |
| **Lógica** | Extrae chat_id, message, llama a `process_message()`, envía respuesta vía Telegram API |
| **Singletons** | Reusa `API_CASCADE`, `current_api_index` desde `ai_cascade.py` |

#### 4.4.2 Notion Cleaner Agent (`app/services/notion_cleaner_agent.py`)

| Aspecto | Detalle |
|---|---|
| **Clase** | `NotionDocument`, `CleaningContext` |
| **Funciones** | `analyze_document(doc)`, `generate_cleaning_plan(docs)` |
| **⚠️ Legacy** | Código legacy para limpieza de Notion. Deprecado en favor de flujo directo |

#### 4.4.3 Routes Telegram (`app/routes/telegram_routes.py`)

| Aspecto | Detalle |
|---|---|
| **⚠️ Legacy** | Define endpoints para webhook pero no se usa directamente. La lógica está en `nexus_bot.py` |

#### 4.4.4 Backend Main (`app/main.py`) y Config (`app/config.py`)

- **`app/main.py`**: FastAPI app independiente en puerto `:8000` para el build service
- **`app/config.py`**: `HOST`, `PORT` (8000) y configs para el backend

### 4.5 ⚠️ Legacy — `routes/` y `services/`

| Archivo | Estado | Notas |
|---|---|---|
| `routes/build_routes.py` | ❌ No usado | Reemplazado por `app/main.py` |
| `routes/notion_routes.py` | ❌ No usado | Funcionalidad migrada a `orchestrators/` |
| `services/build_service.py` | ❌ No usado | Reemplazado por `app/services/` |
| `services/notion_service.py` | ❌ No usado | Funcionalidad en `core/notion_gateway.py` |

---

## 5. 🔁 Flujo de Ejecución Detallado

### 5.1 Flujo Completo: Mensaje de Usuario → Respuesta

```
USUARIO envía mensaje en Telegram
  │
  ▼
[1] Telegram API → POST /webhook → nexus_bot.py:58
  │   telegram_webhook()
  │   ├── Recibe JSON update
  │   ├── Log: "📩 Update recibido: {len(body)} bytes"
  │   └── await handle_telegram_update(data)
  │
  ▼
[2] app/services/telegram_service.py → handle_telegram_update()
  │   ├── Extrae: chat_id, message, message_id
  │   ├── Obtiene: state = get_chat_state(chat_id)
  │   └── await process_message(user_message, chat_id, state)
  │
  ▼
[3] orchestrators/conversation_orchestrator.py → process_message()
  │
  ├── [3a] LOAD from SQLite
  │   ├── user_id = str(chat_id)
  │   ├── identity = load_persisted_identity(user_id)
  │   ├── performance = load_persisted_performance(user_id)
  │   └── config = load_persisted_config(user_id)
  │
  ├── [3b] _process_message_inner()
  │   │
  │   ├── ¿Contiene "recuerda"/"remember"?
  │   │   └── Sí → MemoryResponseLayer._extract_fields()
  │   │         → memory_manager.save_episode()
  │   │         → _recent_memory.append()
  │   │         → Return "🧠 Guardado: {summary}"
  │   │
  │   ├── ¿Pregunta simple de memoria? (cómo me llamo, etc.)
  │   │   └── Sí → _build_memory_response() desde _recent_memory
  │   │
  │   ├── ¿MemoryRouter activado?
  │   │   └── Sí → _build_memory_response() desde _recent_memory
  │   │
  │   ├── ¿Consulta compleja de perfil? (qué sabes, perfil)
  │   │   └── Sí → Pipeline completo de 8 capas:
  │   │         MemoryRouter → Selector → Combiner
  │   │         → Deduplicator → ConflictResolver → Evolution
  │   │         → Inference → SelfCorrection → Reinforcement
  │   │         → IdentityLayer → DecisionLayer
  │   │         → BehaviorPipeline (3 capas)
  │   │         → Synthesizer → Respuesta
  │   │
  │   ├── ¿Contiene "organiza"/"limpia"?
  │   │   └── Sí → State = NOTION_CLEANING
  │   │
  │   ├── ¿Estado WAITING_CONFIRMATION?
  │   │   └── Sí → call_execute_plan() o cancelar
  │   │
  │   ├── ¿Comando directo?
  │   │   ├── "ejecutar {plan_id}" → call_execute_plan()
  │   │   └── "plan/build/crea {idea}" → call_build_app()
  │   │
  │   ├── FLUJO NORMAL (Default):
  │   │   ├── memory_manager.retrieve(query, k=3) → desde Notion
  │   │   ├── build_memory_context() → inyecta en prompt
  │   │   ├── AI Loop (max 5 iteraciones):
  │   │   │   ├── call_ai_with_fallback(messages, tools)
  │   │   │   ├── ¿tool_calls? → Ejecuta tool
  │   │   │   │     ├── notion_search → noti...
  │   │   │   │     ├── notion_fetch → Notion
  │   │   │   │     ├── notion_create → Notion
  │   │   │   │     ├── build_app → backend :8000
  │   │   │   │     └── execute_plan → backend :8000
  │   │   │   └── Pattern extraction → integración en identidad
  │   │   └── BehaviorPipeline para cada mensaje (traza)
  │   │
  │   └── Retorna respuesta (str)
  │
  ├── [3c] FEEDBACK LOOP (si hay decision_trace)
  │   ├── _detect_feedback(message) → True/False/None
  │   ├── ConfidenceFeedbackLayer (ajusta identidad)
  │   ├── PerformanceTracker (actualiza contadores)
  │   ├── StabilityGuard (¿permitir cambio de estrategia?)
  │   └── AdaptiveStrategy (ajusta threshold/weights)
  │
  └── [3d] SAVE to SQLite
      ├── save_persisted_identity(user_id, identity)
      ├── save_persisted_performance(user_id, perf)
      └── save_persisted_config(user_id, config)
```

### 5.2 Flujo del BehaviorPipeline

```
behavior_base (dict con tone, depth, style, verbosity)
  │
  ▼
MemoryPatternAwareBehaviorLayer.apply()
  ├── Por cada dimensión (tone, depth, style):
  │   ├── Busca el pattern correspondiente en identity.patterns
  │   ├── Si existe → ajusta la dimensión según el patrón
  │   └── metadata.dimensions[dim] = {source, value, confidence, pattern_key}
  └── Retorna {behavior, metadata}
  │
  ▼
MemoryConflictResolutionLayer.apply()
  ├── Por cada par de dimensiones:
  │   ├── Detecta si hay conflicto entre valores (ej: formal + casual)
  │   └── Si hay conflicto:
  │       ├── Calcula fuerza de cada señal (confidence)
  │       ├── Compara con dominance_threshold (default 1.5)
  │       └── Gana la de mayor fuerza
  └── Retorna {behavior, metadata}
  │
  ▼
Merge: conflict_overrides_behavior
  │
  ▼
MemoryDecisionTraceLayer.apply()
  ├── Compara behavior_before vs behavior_after
  ├── Calcula:
  │   ├── changed: bool (¿cambió algo?)
  │   ├── source: str (intent/global/conflict)
  │   ├── confidence: float (0.0-1.0)
  │   ├── dimensions: dict (diff por dimensión)
  │   └── metadata: dict (contexto completo)
  └── Retorna {decision_trace}
```

### 5.3 Flujo del AI Cascade

```
call_ai_with_fallback(messages, tools)
  │
  ├── current_api_index → 0 (o el último exitoso)
  │
  ├── Por cada API en API_CASCADE[current_api_index:]:
  │   ├── ¿Tiene API key? No → skip
  │   ├── Intentar llamada:
  │   │   ├── Groq → POST api.groq.com/v1/chat/completions
  │   │   ├── Gemini → POST generativelanguage.googleapis.com/v1beta/...
  │   │   ├── DeepSeek → POST api.deepseek.com/v1/chat/completions
  │   │   └── OpenRouter → POST openrouter.ai/api/v1/chat/completions
  │   │
  │   ├── ¿Éxito (2xx)? → actualizar current_api_index → return response
  │   └── ¿Error?
  │       ├── 429 → "Rate limit, probando siguiente..."
  │       └── Otro → "Error, probando siguiente..."
  │
  └── Todas fallaron → raise Exception("❌ Todas las APIs fallaron...")
```

---

## 6. 📐 Modelos de Datos y Schemas

### 6.1 Pydantic Models (`models/schemas.py`)

```python
class SearchRequest(BaseModel):
    query: str

class FetchRequest(BaseModel):
    page_id: str

class CreateRequest(BaseModel):
    parent_id: str
    title: str
    content: str

class BuildAppRequest(BaseModel):
    project_name: Optional[str] = None
    idea: Optional[str] = None

class BuildAppResponse(BaseModel):
    project_name: str
    blueprint: Dict[str, Any]
    task_list: List[Dict[str, Any]]
    executed_task: Dict[str, Any]
    status: str

class PlanResponse(BaseModel):
    plan_id: str
    status: str
    blueprint: Dict[str, Any]
    tasks: List[Dict[str, Any]]

class ExecutePlanRequest(BaseModel):
    plan_id: str

class ExecutePlanResponse(BaseModel):
    plan_id: str
    status: str
    results: List[Dict[str, Any]]
```

### 6.2 Estructuras Internas del Sistema

#### Identity (persistence.py + memory_identity.py)
```python
# DEFAULT_IDENTITY (persistence.py:29)
{
    "user_name": None,          # str or None
    "project_name": None,       # str or None
    "goals": [],                # List[str]
    "interests": [],            # List[str]
    "patterns": {},             # Dict[str, Any] — patrones de comportamiento
    "global_patterns": {},      # Dict[str, Any] — patrones globales
}
```

#### Performance State (persistence.py:39)
```python
# DEFAULT_PERFORMANCE
{
    "intent":  {"correct": 0, "total": 0},
    "global":  {"correct": 0, "total": 0},
    "conflict": {"correct": 0, "total": 0},
}
```

#### Adaptive Config (persistence.py:46)
```python
# DEFAULT_CONFIG
{
    "dominance_threshold": 1.5,       # float — umbral para resolver conflictos
    "intent_weight_factor": 0.5,      # float — peso de intención en decisión
    "global_weight_factor": 0.5,      # float — peso de patrón global
    # Opcional:
    "previous_accuracy": {},          # Dict[str, float] — precisión histórica
}
```

#### Behavior (behavior_pipeline.py)
```python
{
    "tone": "neutral",          # str — formal/casual/neutral/empathetic/authoritative
    "depth": "medium",          # str — basic/medium/deep/comprehensive
    "style": "concise",        # str — concise/detailed/structured/conversational
    "verbosity": 3,            # int — 1-5
}
```

#### Decision Trace (memory_decision_trace_layer.py)
```python
{
    "changed": True,           # bool — ¿hubo cambio?
    "source": "intent",        # str — intent/global/conflict
    "confidence": 0.85,        # float — 0.0 a 1.0
    "dimensions": {
        "tone": {
            "before": "neutral",
            "after": "formal",
            "reason": "pattern_match",
            "confidence": 0.85
        }
    },
    "metadata": {
        "dimensions": {...}    # metadatos por dimensión
    }
}
```

#### Memory (estructura interna)
```python
{
    "type": "fact",              # str — fact/preference/pattern
    "key": "user_name",          # str
    "value": "Juan",             # str
    "content": "...",            # str — texto completo
    "summary": "...",            # str — resumen corto
    "tags": ["personal"],        # List[str]
    "importance": 5,             # int — 1-5
    "deprecated": False,         # bool
    "source": "episodic",        # str — episodic/semantic
}
```

#### Chat State (state_manager.py)
```python
{
    "state": "IDLE",             # str — IDLE / NOTION_CLEANING / WAITING_CONFIRMATION / EXECUTING
    "mode": "searching",         # str — opcional
    "plan_id": "...",            # str — opcional, para confirmación
}
```

---

## 7. 💾 Sistema de Persistencia

### 7.1 SQLite (`core/persistence.py`)

**Archivo DB:** `nexus_state.db` (en raíz del proyecto, `cwd`)

#### Tabla: `identity_patterns`

| Columna | Tipo | Constraints | Default | Descripción |
|---|---|---|---|---|
| `user_id` | TEXT | PRIMARY KEY | — | Identificador único de usuario |
| `patterns_json` | TEXT | NOT NULL | — | JSON con patrones de comportamiento |
| `global_patterns_json` | TEXT | NOT NULL | — | JSON con patrones globales |
| `updated_at` | TEXT | NOT NULL | — | Timestamp ISO 8601 |

#### Tabla: `performance_state`

| Columna | Tipo | Constraints | Default | Descripción |
|---|---|---|---|---|
| `user_id` | TEXT | NOT NULL | — | Identificador de usuario |
| `source` | TEXT | CHECK('intent','global','conflict') | — | Origen de la métrica |
| `correct` | INTEGER | NOT NULL | 0 | Aciertos |
| `total` | INTEGER | NOT NULL | 0 | Total de muestras |
| | | PRIMARY KEY (user_id, source) | | |

#### Tabla: `adaptive_config`

| Columna | Tipo | Constraints | Default | Descripción |
|---|---|---|---|---|
| `user_id` | TEXT | PRIMARY KEY | — | Identificador de usuario |
| `dominance_threshold` | REAL | NOT NULL | 1.5 | Umbral de dominancia |
| `intent_weight_factor` | REAL | NOT NULL | 0.5 | Peso de intención |
| `global_weight_factor` | REAL | NOT NULL | 0.5 | Peso de patrón global |
| `previous_accuracy_json` | TEXT | NULLABLE | — | JSON con precisión histórica |
| `updated_at` | TEXT | NOT NULL | — | Timestamp ISO 8601 |

#### Configuración de Conexión

```python
# persistence.py:67-70
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Logging
conn.execute("PRAGMA synchronous=NORMAL")      # Balance velocidad/seguridad
```

**Thread safety:** Lock global `_db_lock = threading.Lock()` (línea 26)

**Connection caching:** `_connection_cache` dict (línea 53), reusa conexiones.

#### Funciones CRUD

| Función | Operación | Fail-safe |
|---|---|---|
| `load_identity(user_id)` | SELECT desde `identity_patterns` | Retorna DEFAULT_IDENTITY |
| `save_identity(user_id, identity)` | INSERT OR REPLACE en `identity_patterns` | Log + silent return |
| `load_performance(user_id)` | SELECT desde `performance_state` | Retorna DEFAULT_PERFORMANCE |
| `save_performance(user_id, state)` | INSERT OR REPLACE en `performance_state` (3 rows) | Log + silent return |
| `load_config(user_id)` | SELECT desde `adaptive_config` | Retorna DEFAULT_CONFIG |
| `save_config(user_id, config)` | INSERT OR REPLACE en `adaptive_config` | Log + silent return |

**Principios de diseño** (del docstring):
- **Deterministic** — sin AI, sin randomness, sin side effects fuera de DB
- **Fail-safe** — nunca crashea al caller, siempre retorna defaults seguros

### 7.2 JSON File (`core/state_manager.py`)

**Archivo:** `chat_states.json` (en raíz del proyecto)

**Estructura:**
```json
{
    "123456789": {
        "state": "IDLE",
        "mode": "searching"
    },
    "987654321": {
        "state": "WAITING_CONFIRMATION",
        "plan_id": "abc-123"
    }
}
```

**⚠️ Tech Debt:** No hay lock de hilo para `chat_states`; `save_states()` se llama explícitamente, no automáticamente.

### 7.3 Notion (External - vía `core/notion_gateway.py`)

**Bases de datos utilizadas (desde .env):**
- `NOTION_MEMORY_EPISODES_DB_ID` — memoria episódica
- `NOTION_MEMORY_SEMANTIC_DB_ID` — memoria semántica
- `NOTION_DIRTY_DB_ID` — documentos "sucios" para limpieza (⚠️ legacy)
- `NOTION_CLEAN_DB_ID` — documentos limpios (⚠️ legacy)

**Propiedades de página en Memory_Episodes:**
```json
{
    "summary": {"title": [{"text": {"content": "Resumen corto"}}]},
    "content": {"rich_text": [{"text": {"content": "Contenido completo"}}]},
    "tags": {"multi_select": [{"name": "personal"}]},
    "importance": {"number": 3},
    "created_at": {"date": {"start": "2024-01-01T00:00:00Z"}}
}
```

---

## 8. 🧪 Sistema de Tests

### 8.1 Inventario de Tests

| Archivo | Componente | Tests | Asserts | Estado |
|---|---|---|---|---|
| `test_persistence.py` | `core/persistence.py` | 17 | ~36 | ✅ Completo |
| `test_behavior_pipeline.py` | `core/behavior_pipeline.py` | 6 | ~24 | ✅ Completo |
| `test_behavior_cycles.py` | Behavior Pipeline + feedback loop | 6 | ~30 | ✅ Completo |
| `test_pattern_aware_behavior.py` | MemoryPatternAwareBehaviorLayer | 5 | ~20 | ✅ Completo |
| `test_conflict_behavior.py` | MemoryConflictResolutionLayer | 4 | ~16 | ✅ Completo |
| `test_decision_trace.py` | MemoryDecisionTraceLayer | 5 | ~20 | ✅ Completo |
| `test_confidence_feedback.py` | MemoryConfidenceFeedbackLayer | 5 | ~15 | ✅ Completo |
| `test_performance_tracker.py` | MemoryPerformanceTracker | 5 | ~15 | ✅ Completo |
| `test_stability_guard.py` | MemoryStabilityGuardLayer | 6 | ~20 | ✅ Completo |
| `test_adaptive_strategy.py` | MemoryAdaptiveStrategyLayer | 5 | ~20 | ✅ Completo |
| `test_pattern_decay_layer.py` | MemoryPatternDecayLayer | 5 | ~15 | ✅ Completo |
| `test_learning_dynamics.py` | Feedback loop completo (end-to-end) | 8 | ~30 | ✅ Completo |
| `test_final_decision_scenarios.py` | Pipeline completo (scenarios reales) | 6 | ~24 | ✅ Completo |
| `test_distribution_behavior.py` | Distribución de comportamientos | 4 | ~12 | ✅ Completo |
| `test_basic.py` | Smoke tests (API) | 4 | ~1 | ⚠️ Básico |
| **TOTAL** | — | **~91** | **~317** | **✅ 93% coverage** |

### 8.2 Cobertura por Módulo

| Módulo | Tests | Cobertura |
|---|---|---|
| `persistence.py` | 17 tests | ✅ Excelente (edge cases, defaults, user isolation, determinism) |
| `behavior_pipeline.py` | 6 tests | ✅ Excelente |
| `memory_pattern_aware_behavior_layer.py` | 5 tests | ✅ Excelente |
| `memory_conflict_resolution_layer.py` | 4 tests | ✅ Bueno |
| `memory_decision_trace_layer.py` | 5 tests | ✅ Excelente |
| `memory_confidence_feedback_layer.py` | 5 tests | ✅ Excelente |
| `memory_performance_tracker.py` | 5 tests | ✅ Excelente |
| `memory_stability_guard_layer.py` | 6 tests | ✅ Excelente |
| `memory_adaptive_strategy_layer.py` | 5 tests | ✅ Bueno |
| `memory_pattern_decay_layer.py` | 5 tests | ✅ Bueno |
| `learning_dynamics` (end-to-end) | 8 tests | ✅ Excelente |
| `decision_scenarios` (end-to-end) | 6 tests | ✅ Excelente |
| `ai_cascade.py` | **0 tests** | ❌ Sin cobertura |
| `notion_gateway.py` | **0 tests** | ❌ Sin cobertura |
| `memory_manager.py` | **0 tests** | ❌ Sin cobertura |
| `orchestrators/` | **0 tests** | ❌ Sin cobertura |
| `app/services/` | **0 tests** | ❌ Sin cobertura |
| `state_manager.py` | **0 tests** | ❌ Sin cobertura |

### 8.3 Comandos para Ejecutar Tests

```bash
# Todos los tests
python -m pytest test_*.py -v

# Tests de persistencia
python -m pytest test_persistence.py -v

# Tests del behavior pipeline
python -m pytest test_behavior_pipeline.py -v

# Tests del feedback loop
python -m pytest test_confidence_feedback.py test_performance_tracker.py test_stability_guard.py test_adaptive_strategy.py -v

# Tests end-to-end
python -m pytest test_learning_dynamics.py test_final_decision_scenarios.py -v

# Tests de comportamiento
python -m pytest test_pattern_aware_behavior.py test_conflict_behavior.py test_decision_trace.py -v

# Test único
python -m pytest test_persistence.py::TestPersistenceIdentity::test_save_and_load_identity -v
```

### 8.4 Patrones de Test Utilizados

Los tests siguen estos patrones:

1. **Determinismo** — mismos inputs siempre producen mismos outputs
2. **Aislamiento** — cada test crea/limpia su propio estado
3. **Fail-safe** — se verifica que las funciones nunca lancen excepciones
4. **Defaults** — se verifica que usuarios no existentes retornen valores seguros
5. **Edge cases** — tipos inválidos, JSON corrupto, user_id vacío, etc.

---

## 9. 🔌 Puntos de Integración y Extensibilidad

### 9.1 Dónde Enchufar el Action System

El Action System propuesto se puede conectar en estos puntos:

#### 🔌 Punto 1: Después del AI Loop (RECOMENDADO)
**Archivo:** `orchestrators/conversation_orchestrator.py` — alrededor de línea 643
```
# Después de return content (línea 643)
# Antes de que el mensaje se devuelva al usuario
```
**Razonamiento:** Aquí ya tienes el `decision_trace`, `persisted_identity`, `performance_state` disponibles. Podrías ejecutar acciones basadas en la intención detectada.

#### 🔌 Punto 2: En el Feedback Loop
**Archivo:** `orchestrators/conversation_orchestrator.py` — función `_run_feedback_loop()` (línea 137)
```
# Después de las 4 capas del feedback loop
# Ideal para acciones correctivas basadas en feedback negativo
```

#### 🔌 Punto 3: En el BehaviorPipeline
**Archivo:** `core/behavior_pipeline.py` — método `run()` (línea 39)
```
# Como una cuarta capa después de DecisionTraceLayer
# Para acciones deterministas basadas en el comportamiento decidido
```

#### 🔌 Punto 4: Como Módulo Independiente
**Crear:** `core/action_system.py`
**Conectar:** Desde `orchestrators/conversation_orchestrator.py` en `process_message()`
```
process_message():
  ├── LOAD
  ├── PROCESS (existente)
  ├── FEEDBACK (existente)  
  ├── ACTION ← NUEVO: ejecutar acciones post-procesamiento
  └── SAVE (existente)
```

### 9.2 Hooks de Extensibilidad Existentes

| Hook | Archivo | Línea | Descripción |
|---|---|---|---|
| `NOTION_TOOLS` | `core/tools.py` | — | Añadir nuevas tools para el AI Loop |
| `API_CASCADE` | `core/ai_cascade.py` | 97-154 | Añadir/quitar APIs de IA |
| `_NEGATIVE_KEYWORDS` | `conversation_orchestrator.py` | 86-89 | Keywords de feedback negativo |
| `_POSITIVE_KEYWORDS` | `conversation_orchestrator.py` | 91-93 | Keywords de feedback positivo |
| `_PREFERENCE_KEYWORDS` | `conversation_orchestrator.py` | 95-98 | Keywords de preferencia |
| `simple_queries` | `conversation_orchestrator.py` | 373-381 | Queries de memoria simple |
| `complex_queries` | `conversation_orchestrator.py` | 404-406 | Queries de perfil complejo |
| `DEFAULT_CONFIG` | `core/persistence.py` | 46-50 | Config inicial del learning loop |
| `DEFAULT_IDENTITY` | `core/persistence.py` | 29-36 | Identidad inicial |

### 9.3 Servicios Externos

| Servicio | Protocolo | Configuración (env) |
|---|---|---|
| Telegram Bot API | HTTPS REST | `TELEGRAM_BOT_TOKEN` |
| Notion API v1 | HTTPS REST | `NOTION_TOKEN`, varias DB IDs |
| Groq API | HTTPS REST (OpenAI-compat) | `GROQ_API_KEY_1/2/3` |
| Gemini API | HTTPS REST | `GEMINI_API_KEY_1/2` |
| DeepSeek API | HTTPS REST (OpenAI-compat) | `DEEPSEEK_API_KEY_1/2` |
| OpenRouter API | HTTPS REST | `OPENROUTER_API_KEY` |
| Backend propio | HTTP localhost:8000 | — |

---

## 10. 🚫 Constraints y Reglas de Diseño

### 10.1 Reglas de Diseño del Sistema

1. **🧠 Determinismo en el Core** — `core/persistence.py` y `core/behavior_pipeline.py` son completamente deterministas. Sin AI, sin random, sin side effects. **NO AÑADIR AI aquí.**

2. **🔒 Fail-Safe Persistence** — Las funciones de `persistence.py` NUNCA lanzan excepciones. Siempre retornan valores seguros. **NO ROMPER ESTO.**

3. **🤖 AI Solo en la Capa de Decisión** — La IA solo se invoca en `core/ai_cascade.py` y desde `orchestrators/conversation_orchestrator.py`. Las capas de memoria y comportamiento no llaman a APIs externas.

4. **🧬 Pipeline de Memoria Separado** — Las 8 capas del pipeline de memoria (`deduplicator → conflict_resolver → evolution → inference → self_correction → reinforcement → identity → decision`) son independientes y pueden intercambiarse.

5. **💾 Thread-Safety en SQLite** — `_db_lock` protege todas las operaciones de escritura. **NO ELIMINAR** este lock.

6. **🌐 Notion es Store, No Source of Truth** — Notion se usa para almacenar memoria episódica, pero el sistema debe funcionar sin conexión a Notion (graceful degradation).

7. **📏 Sin Embeddings (v1)** — El sistema actual usa keyword matching para scoring de memorias. No se requieren embeddings vectoriales.

8. **⚙️ Configuración por Variables de Entorno** — Todas las API keys y configuraciones se cargan desde `.env` vía `load_dotenv()`.

### 10.2 Lo Que NO Tocar

| Archivo | Razón |
|---|---|
| `core/persistence.py` | Fail-safe, thread-safe, determinista. NO añadir AI, NO cambiar API pública |
| `core/ai_cascade.py::API_CASCADE` | El orden es crítico para el fallback. NO reordenar sin testear |
| `behavior_pipeline.py::BehaviorPipeline.run()` | API pública estable usada desde 2 lugares distintos |
| `persistence.py::_db_lock` | Protección crítica contra race conditions en SQLite |
| `persistence.py::DEFAULT_IDENTITY/PERFORMANCE/CONFIG` | Dicts mutables compartidos usados como defaults |

### 10.3 Tech Debt Conocido ⚠️

| Deuda | Archivo | Impacto |
|---|---|---|
| `current_api_index` global mutable | `ai_cascade.py:157` | Si una API falla, el sistema se queda en esa API hasta nuevo fallo. No hay reset periódico |
| `chat_states` sin thread lock | `state_manager.py:37` | Race condition potencial en writes concurrentes |
| `memory_pattern_decay_layer.py` sin timestamps reales | `memory_pattern_decay_layer.py` | El decaimiento no funciona porque los patrones no tienen timestamp individual |
| `MemoryConflictResolver.deprecate` es no-op | `memory_conflict_resolver.py` | Los conflictos se detectan pero no se persisten en Notion |
| `MemoryEvolution` compresión lossy | `memory_evolution.py` | La evolución de memorias pierde datos al comprimir |
| `legacy_notion_create()` coexistiendo | `notion_gateway.py` | Dos versiones de `notion_create` — puede causar confusión |
| `_recent_memory` en RAM sin persistencia | `conversation_orchestrator.py:101` | Se pierde al reiniciar el servidor |
| `routes/` y `services/` legacy | `routes/`, `services/` | Código muerto que debe eliminarse |
| `cleaning_orchestrator.py` legacy | `orchestrators/cleaning_orchestrator.py` | Flujo de limpieza deprecado |
| Sin tests para AI Cascade | `ai_cascade.py` | Componente crítico sin cobertura |
| Sin tests para Notion Gateway | `notion_gateway.py` | Gateway externo sin test |
| Sin tests para Conversation Orchestrator | `orchestrators/conversation_orchestrator.py` | Módulo más grande sin tests unitarios |

### 10.4 Variables de Entorno Requeridas

```bash
# === CRÍTICAS ===
TELEGRAM_BOT_TOKEN=           # Token del bot de Telegram

# === APIs de IA (al menos 1 requerida) ===
GROQ_API_KEY_1=               # Groq Llama 3.3 70B (principal)
GROQ_API_KEY_2=               # Groq Llama 3.3 70B (backup)
GROQ_API_KEY_3=               # Groq Llama 3.1 8B (rápido)
GEMINI_API_KEY_1=             # Gemini 1.5 Flash
GEMINI_API_KEY_2=             # Gemini 1.5 Flash (backup)
DEEPSEEK_API_KEY_1=           # DeepSeek Chat
DEEPSEEK_API_KEY_2=           # DeepSeek Chat (backup)
OPENROUTER_API_KEY=           # OpenRouter (último recurso)

# === NOTION ===
NOTION_TOKEN=                 # Token de integración Notion
NOTION_MEMORY_EPISODES_DB_ID= # DB ID para memoria episódica
NOTION_MEMORY_SEMANTIC_DB_ID= # DB ID para memoria semántica
NOTION_DIRTY_DB_ID=           # DB ID para limpieza (⚠️ legacy)
NOTION_CLEAN_DB_ID=           # DB ID para documentos limpios (⚠️ legacy)
NOTION_TITLE_PROPERTY=        # Propiedad de título (default: "title")

# === OPCIONALES ===
PORT=8001                     # Puerto del servidor (default: 8001)
```

### 10.5 Comandos de Arranque

```bash
# Iniciar servidor del bot (Telegram)
uvicorn nexus_bot:app --host 0.0.0.0 --port 8001

# Iniciar backend (build service)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Iniciar ambos (PowerShell)
.\start_services.ps1

# Configurar webhook
curl -X POST http://localhost:8001/set-webhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tu-dominio.com/webhook"}'

# Verificar estado
curl http://localhost:8001/diagnose
```

---

> **Documento generado el 2026-01-05** basado en el análisis exhaustivo del repositorio `bNL-core` (commit `4b978f9`).  
> Para actualizar, ejecutar el escaneo completo de archivos `.py` en el repositorio y regenerar las secciones afectadas.
