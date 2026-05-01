# 🗺️ System Map — NexusAgentes

> **Date:** 28/04/2026
> **Type:** Full architectural map of the Nexus BNL system

---

## 1. SYSTEM OVERVIEW

NexusAgentes (Nexus BNL v3.0) is an **autonomous AI development agency** that runs as a **Telegram bot** with:

- **Multi-API AI fallback cascade** — 8 providers (Groq ×3, Gemini ×2, DeepSeek ×2, OpenRouter ×1) in priority order
- **Notion integration** — read, search, create, update pages as a knowledge base
- **App building pipeline** — generates project blueprints and executes plans via a local FastAPI backend
- **Memory system** — episodic memory stored in Notion with retrieval, ranking, and synthesis
- **Behavior decision pipeline** — deterministic pattern-aware system that adjusts tone, depth, and style based on accumulated user patterns
- **Cleaning flow** — AI-powered Notion page analysis and structured knowledge extraction

The system has **two coexisting architectures**: a legacy sync stack (`services/`, `routes/` root) and a modern async stack (`core/`, `orchestrators/`, `app/`). The modern stack is the active one.

### Main Capabilities

| Capability | Description |
|---|---|
| **Memory** | Episodic storage in Notion DBs + RAM cache + retrieval/ranking/synthesis |
| **Behavior Decision** | Deterministic pipeline that adapts response style from accumulated user patterns |
| **Feedback Loop** | Confidence-based pattern weight adjustment from feedback signals |
| **Performance Tracking** | Success rate tracking per decision source (intent, global, conflict) |
| **Adaptive Strategy** | Dynamic tuning of thresholds based on performance metrics |
| **Stability Guard** | Minimum data requirements and noise gates before strategy updates |
| **Conflict Resolution** | Resolves weak signal conflicts between intent-specific and global patterns |
| **Self-Correction** | Detects and resolves memory conflicts in persistent storage |
| **Pattern Decay** | Controlled weight reduction to prevent unbounded growth |
| **Multi-API Fallback** | 8 AI providers in cascade with automatic failover |

---

## 2. CORE PIPELINE

### 2.1 Behavior Decision Pipeline (Deterministic, No AI)

```
MemoryPatternIntegrator
  → MemoryPatternDecayLayer
  → MemoryGlobalPatternLayer
  → MemoryPatternAwareBehaviorLayer
  → MemoryConflictResolutionLayer
  → MemoryDecisionTraceLayer
  → MemoryConfidenceFeedbackLayer
  → MemoryPerformanceTracker
  → MemoryAdaptiveStrategyLayer
  → MemoryStabilityGuardLayer
```

This pipeline is wrapped by **BehaviorPipeline** which runs three layers:
```
BehaviorPipeline.run(intent, behavior, identity)
  │
  ├─ STEP 1: MemoryPatternAwareBehaviorLayer
  │     Adjusts tone/depth/style using intent-specific patterns
  │     Fallback: global_patterns if no intent-specific dominance
  │
  ├─ STEP 2: MemoryConflictResolutionLayer
  │     Resolves weak signals by combining intent + global with adaptive weighting
  │     Only triggers when no strong decision was made in STEP 1
  │
  └─ STEP 3: MemoryDecisionTraceLayer
        Captures structured trace (source, confidence, signal strengths)
        Returns decision_trace alongside final behavior
```

### 2.2 Memory Retrieval & Synthesis Pipeline (Conversational Context)

```
MemoryRouter (should_use_memory?)
  → MemoryManager.retrieve (Notion DB query)
  → MemorySelector (rank by relevance)
  → MemoryCombiner
  → MemoryDeduplicator
  → MemoryConflictResolver
  → MemoryEvolution
  → MemoryInference
  → MemorySelfCorrectionLayer (persistent deprecation)
  → MemoryReinforcementLayer (persistent reinforcement)
  → MemoryIdentityLayer (build identity profile)
  → MemoryDecisionLayer (filter, re-score, diverse selection)
  → MemoryAdaptiveBehaviorLayer (determine tone/depth/style/verbosity)
  → MemorySynthesizer (final response string)
```

### 2.3 Conversation Flow (process_message in orchestrators/conversation_orchestrator.py)

```
process_message(user_message, chat_id, state)
  │
  ├─ 1. DIRECT MEMORY CAPTURE
  │     "recuerda" / "remember" → extract key+value → save_episode → RAM cache
  │
  ├─ 2. SIMPLE MEMORY FALLBACK
  │     Predefined queries → RAM cache lookup → response
  │
  ├─ 3. MEMORY ROUTER
  │     should_use_memory() → RAM cache → MemorySelector → response
  │
  ├─ 4. COMPLEX PROFILE QUERIES
  │     Full pipeline: Deduplicator → ConflictResolver → Evolution → Inference
  │     → SelfCorrection → Reinforcement → IdentityLayer → DecisionLayer
  │     → AdaptiveBehaviorLayer → Synthesizer
  │
  ├─ 5. NOTION CLEANING FLOW
  │     "organiza"/"limpia" → searching → reviewing → confirm → APPLY → saved
  │
  ├─ 6. DIRECT COMMANDS
  │     "ejecutar {id}" → execute_plan
  │     "plan/build/crea {idea}" → build_app
  │
  └─ 7. AI LOOP (normal flow)
        Memory context injection → AI cascade with function calling
        notion_search / notion_fetch / notion_create / build_app / execute_plan
```

---

## 3. COMPONENT MAP

### 3.1 Behavior Decision System (core/)

#### MemoryPatternIntegrator
- **Responsibility:** Accumulates pattern signals into `identity["patterns"]`
- **Inputs:** `{"pattern_signals": [...], "identity": {...}}`
- **Outputs:** `{"identity": {...}}` with updated patterns
- **Dependencies:** None (pure function)
- **Key rules:** Only adds weights (setdefault + +=). Never removes. No normalization. No decay.

#### MemoryPatternDecayLayer
- **Responsibility:** Applies controlled decay to all pattern weights
- **Inputs:** `{"identity": {...}}`
- **Outputs:** `{"identity": {...}}` with decayed/pruned patterns
- **Dependencies:** None (pure function)
- **Key rules:** DECAY_FACTOR = 0.995, PRUNE_THRESHOLD = 0.05

#### MemoryGlobalPatternLayer
- **Responsibility:** Aggregates pattern weights across all intents into `identity["global_patterns"]`
- **Inputs:** `{"identity": {...}}`
- **Outputs:** `{"identity": {...}}` with added `global_patterns`
- **Dependencies:** None (pure function)
- **Key rules:** Sums same values across intents. Does NOT modify original patterns.

#### MemoryPatternAwareBehaviorLayer
- **Responsibility:** Adjusts tone, depth, style using intent-specific and global patterns
- **Inputs:** `{"intent": str, "behavior": {...}, "identity": {...}}`
- **Outputs:** `{"behavior": {...}, "metadata": {"dimensions": {...}}}`
- **Dependencies:** None (pure function)
- **Key rules:** 1.5× dominance threshold. Requires ≥2 values per intent. Fallback to global patterns.

#### MemoryConflictResolutionLayer
- **Responsibility:** Resolves conflicts between weak intent and global signals
- **Inputs:** `{"intent": str, "behavior": {...}, "identity": {...}}`
- **Outputs:** `{"behavior": {...}, "metadata": {"dimensions": {...}}}`
- **Dependencies:** None (pure function)
- **Key rules:** DOMINANCE_THRESHOLD = 1.3. Adaptive source weighting based on spread.

#### MemoryDecisionTraceLayer
- **Responsibility:** Captures structured trace of behavior decision
- **Inputs:** `{"intent": str, "behavior_before": {...}, "behavior_after": {...}, "identity": {...}, "metadata": {...}}`
- **Outputs:** `{"decision_trace": {...}}`
- **Dependencies:** None (pure function)
- **Key outputs:** source ("intent"/"global"/"conflict"/"mixed"/"none"), confidence (ratio top/second), per-dimension details

#### MemoryConfidenceFeedbackLayer
- **Responsibility:** Adjusts pattern weights based on decision outcome feedback
- **Inputs:** `{"decision_trace": {...}, "feedback": bool, "identity": {...}}`
- **Outputs:** `{"identity": {...}}`
- **Dependencies:** None (pure function)
- **Key rules:** +0.2 (intent), +0.15 (conflict), +0.1 (global) for positive. Negative for false. Soft cap at MAX_WEIGHT = 10.0.

#### MemoryPerformanceTracker
- **Responsibility:** Tracks success rates per decision source
- **Inputs:** `{"decision_trace": {...}, "feedback": bool, "state": {...}}`
- **Outputs:** `{"state": {...}}` with correct/total per source
- **Dependencies:** None (pure function)

#### MemoryAdaptiveStrategyLayer
- **Responsibility:** Adjusts config parameters based on performance
- **Inputs:** `{"performance_state": {...}, "config": {...}}`
- **Outputs:** `{"config": {...}}` with adjusted thresholds
- **Dependencies:** None (pure function)
- **Key rules:** intent accuracy > 0.7 → +0.1 weight. global accuracy < 0.5 → -0.1 weight. conflict > 0.8 → -0.1 threshold. All clamped.

#### MemoryStabilityGuardLayer
- **Responsibility:** Prevents unstable strategy adjustments
- **Inputs:** `{"performance_state": {...}, "config": {...}}`
- **Outputs:** `{"allow_update": bool}`
- **Dependencies:** None (pure function)
- **Key rules:** MIN_TOTAL=5, STABLE_TOTAL=10, MIN_DELTA=0.05

#### BehaviorPipeline
- **Responsibility:** Orchestrates the complete behavior decision pipeline
- **Inputs:** `{"intent": str, "behavior": {...}, "identity": {...}}`
- **Outputs:** `{"behavior": {...}, "decision_trace": {...}}`
- **Dependencies:** MemoryPatternAwareBehaviorLayer, MemoryConflictResolutionLayer, MemoryDecisionTraceLayer

### 3.2 Memory Retrieval System (core/)

#### MemoryRouter
- **Responsibility:** Decides if a message should be answered from memory vs AI
- **Inputs:** `user_message: str`
- **Outputs:** `bool` (True if memory query detected)
- **Dependencies:** None (rule-based)
- **Key detection:** "como se llama", "recuerdas", "te dije", etc.

#### MemoryDecider
- **Responsibility:** Decides if an interaction should be stored as episodic memory
- **Inputs:** `user_message: str, ai_response: str`
- **Outputs:** `Optional[dict]` with summary, tags, importance
- **Dependencies:** None (rule-based)
- **Key rules:** Explicit keywords → importance 5. High-value patterns → importance 4.

#### MemoryManager
- **Responsibility:** Saves to and retrieves from Notion memory databases
- **Inputs:** `save_episode(content, summary, tags, importance)`, `retrieve(query, k)`
- **Outputs:** Saved episode confirmation / List of normalized memories
- **Dependencies:** `core/notion_gateway.py`
- **Key features:** Query type classification (action/knowledge/contextual), text scoring, recency fallback

#### MemorySelector
- **Responsibility:** Selects and ranks best memory for a query
- **Inputs:** `memories: list, query: str`
- **Outputs:** `dict` (best memory) or `list` (ranked with scores)
- **Dependencies:** None (rule-based scoring)
- **Key features:** Intent detection (user name, project, goal) + word match + tag match + importance + penalties

#### MemoryCombiner
- **Responsibility:** Combines multiple memories into one natural language string
- **Inputs:** `ranked_memories: list`
- **Outputs:** `str` (combined sentence)
- **Dependencies:** MemoryResponseLayer
- **Key rules:** Score threshold ≥ 8. Max 3 items. Merge with "y" conjunctions.

#### MemoryDeduplicator
- **Responsibility:** Removes duplicate values from ranked memories
- **Inputs:** `ranked_memories: list`
- **Outputs:** `list` (deduplicated)
- **Dependencies:** None
- **Key method:** Normalize value → track in set → skip duplicates

#### MemoryConflictResolver
- **Responsibility:** Keeps the highest-scored memory per key
- **Inputs:** `ranked_memories: list`
- **Outputs:** `list` (resolved)
- **Dependencies:** None
- **Key method:** For each key, keep item with max score

#### MemoryEvolution
- **Responsibility:** Marks duplicate memories as "deprecated"
- **Inputs:** `ranked_memories: list`
- **Outputs:** `list` with "status" field added
- **Dependencies:** None
- **Key method:** First occurrence → "active". Subsequent → "deprecated".

#### MemoryInference
- **Responsibility:** Infers context from user's goal
- **Inputs:** `ranked_memories: list`
- **Outputs:** `list` (possibly with added inference item)
- **Dependencies:** None
- **Key rules:** If goal contains AI/agentes keywords → add inference memory

#### MemorySelfCorrectionLayer
- **Responsibility:** Detects and corrects conflicting memories in persistent storage
- **Inputs:** `ranked_memories: list, memory_manager: MemoryManager`
- **Outputs:** Original list (unchanged). Side-effects: deprecate losers + save correction episode.
- **Dependencies:** MemoryManager
- **Key rules:** Score gap ≥ 2 to correct. Ignores "inference" key. Idempotent.

#### MemoryReinforcementLayer
- **Responsibility:** Reinforces repeated memories in persistent storage
- **Inputs:** `ranked_memories: list, memory_manager: MemoryManager`
- **Outputs:** Original list (unchanged). Side-effects: save reinforcement episode.
- **Dependencies:** MemoryManager
- **Key rules:** Count ≥ 2 → reinforce. Reinforcement = min(3, count-1). Importance base=5, capped at 10.

#### MemoryIdentityLayer
- **Responsibility:** Builds user identity profile from memories
- **Inputs:** `ranked_memories: list`
- **Outputs:** `dict` with user_name, project_name, goals, interests, patterns
- **Dependencies:** None
- **Key rules:** user_name/project_name = first found. goals = top 2 by score. interests = score ≥ 8, top 3. patterns = repeated ≥ 2 with score ≥ 7.

#### MemoryDecisionLayer
- **Responsibility:** Filters and re-scores memories based on user message and identity
- **Inputs:** `ranked_memories: list, identity: dict, user_message: str, intent: Optional[str]`
- **Outputs:** `list` (top 5 re-scored, diverse selection)
- **Dependencies:** None (pure function)
- **Key rules:** Word match +3. Identity key +2. Intent adjustments. Noise penalty. Diverse selection (goal > project_name > user_name).

#### MemoryAdaptiveBehaviorLayer
- **Responsibility:** Determines tone, depth, style, verbosity for response
- **Inputs:** `selected_memories: list, identity: dict, query: str, intent: str`
- **Outputs:** `{"tone": str, "depth": str, "style": str, "verbosity": int}`
- **Dependencies:** None (rule-based)
- **Key rules:** tone: action→direct, how→technical, has user_name→casual. depth: action→short, ≥4 memories→deep. style: action→concise, deep→structured. verbosity: min(5, max(1, len)).

#### MemorySynthesizer
- **Responsibility:** Converts memories, identity, and behavior into final response
- **Inputs:** `ranked_memories: list, identity: Optional[dict], behavior: Optional[dict]`
- **Outputs:** `str` (final response)
- **Dependencies:** MemoryResponseLayer
- **Key features:** Identity-driven construction. Behavior-aware (verbosity, depth, tone, style controls). Priority: identity > project > goal > inference > context.

#### MemoryResponseLayer
- **Responsibility:** Converts structured memory to natural language
- **Inputs:** `memory: dict`
- **Outputs:** `str`
- **Dependencies:** None (template-based)
- **Key templates:** "Tu proyecto se llama {value}", "Te llamas {value}", "Tu objetivo es {value}"

### 3.3 Infrastructure (core/)

#### AI Cascade (core/ai_cascade.py)
- **AIProvider** — Enum for 8 providers
- **AttrDict** — dict-to-attribute converter for multi-provider response normalization
- **call_ai_with_fallback()** — tries providers in priority order until one succeeds
- **call_groq()/call_gemini()/call_deepseek()/call_openrouter()** — provider-specific HTTP clients
- **extract_ai_content()** — safe content extraction from any provider response format
- **NEXUS_BNL_SYSTEM_PROMPT** — core system prompt defining bot personality and rules

#### Notion Gateway (core/notion_gateway.py)
- **notion_search(query)** — searches workspace via POST /v1/search
- **notion_fetch(page_id)** — gets page + block children
- **notion_create(database_id, properties, children)** — creates page in database
- **notion_update(page_id, properties)** — updates existing page properties
- **_notion_query_database(database_id, query)** — database-specific title search
- **_fuzzy_match_title(a, b)** — fuzzy comparison via SequenceMatcher
- **build_notion_blocks(title, content, summary)** — builds structured Notion blocks
- **_clean_page_id(page_id)** — normalizes malformed UUIDs

#### State Manager (core/state_manager.py)
- **chat_states** — global dict loaded from/saved to JSON file
- **load_states()/save_states()/get_chat_state()** — CRUD for chat states
- **memory** — three-tier dict (short/medium/long)
- **save_short_memory()/clean_memory()** — temporal memory management

#### Backend Client (core/backend_client.py)
- **_call_backend(endpoint, payload)** — HTTP POST to local backend
- **call_build_app(idea)** → POST /build-app
- **call_execute_plan(plan_id)** → POST /execute-plan

#### Formatters (core/formatters.py)
- **_format_plan_result()** — plan response to Telegram markdown
- **_format_execution_result()** — execution result to Telegram markdown
- **build_memory_context()** — memory list to injectable prompt context

#### Tools (core/tools.py)
- **NOTION_TOOLS** — function calling schemas (notion_search, notion_fetch, notion_create, build_app, execute_plan)

### 3.4 Orchestrators

#### ConversationOrchestrator (orchestrators/conversation_orchestrator.py)
- **process_message()** — main message handler. Routes through memory capture, memory router, complex queries, cleaning flow, direct commands, AI loop.
- **_build_memory_response()** — convenience function for quick memory responses

#### CleaningOrchestrator (orchestrators/cleaning_orchestrator.py)
- **apply_cleaning_result()** — merges AI analysis + user feedback into structured Notion page
- **handle_cleaning_flow()** — manages the searching → reviewing → confirm → APPLY → saved state machine

### 3.5 Agents

#### NotionCleanerAgent (app/services/notion_cleaner_agent.py)
- **analyze_pages(pages)** — sends Notion page content to AI for analysis
- **build_clean_page(content)** — placeholder for structured content building

#### Zombie Agents (agents/)
- **planner.py** — placeholder (optimize_task_plan returns same list)
- **executor.py** — placeholder (run_task returns "pending_execution")
- **blueprint.py** — placeholder (enrich_blueprint returns same dict)

### 3.6 App Layer

#### Telegram Bot Runner (app/main.py)
- **main()** — PTB Application with polling. One handler → process_message.
- **user_states** — in-memory dict per chat_id

#### Web Server (nexus_bot.py)
- **FastAPI app** — legacy webhook-based entry point
- **Endpoints:** /, /webhook, /set-webhook, /webhook-info, /api-status, /diagnose
- **Imports from:** `app/services/telegram_service.py` (deprecated location — now lives in orchestrators/)

---

## 4. DATA FLOW

### 4.1 Identity

```
Structure:
  identity = {
      "user_name": str | None,
      "project_name": str | None,
      "goals": [str],
      "interests": [str],
      "patterns": [str],            # from MemoryIdentityLayer
      "patterns": {                 # from MemoryPatternIntegrator
          "tone": {"greeting": {"formal": 1.5, ...}},
          "depth": {...},
          "style": {...}
      },
      "global_patterns": {          # from MemoryGlobalPatternLayer
          "tone": {"formal": 3.2, "casual": 1.1, ...},
          "depth": {...},
          "style": {...}
      }
  }
```

**Flow:**
1. MemoryPatternIntegrator writes to `identity["patterns"][dimension][intent][value]`
2. MemoryPatternDecayLayer reads/writes from `identity["patterns"]`
3. MemoryGlobalPatternLayer reads `identity["patterns"]`, writes `identity["global_patterns"]`
4. MemoryPatternAwareBehaviorLayer reads both for behavior adjustment
5. MemoryConflictResolutionLayer reads both for conflict resolution
6. MemoryIdentityLayer builds simple identity (user_name, project_name, goals) from ranked memories

### 4.2 Behavior

```
Structure:
  behavior = {
      "tone": "casual" | "technical" | "direct",
      "depth": "short" | "medium" | "deep",
      "style": "structured" | "narrative" | "concise",
      "verbosity": int (1-5)
  }
```

**Flow:**
1. Initial behavior comes from MemoryAdaptiveBehaviorLayer (rule-based)
2. MemoryPatternAwareBehaviorLayer adjusts based on patterns
3. MemoryConflictResolutionLayer adjusts based on weak signal resolution
4. MemoryDecisionTraceLayer captures before/after
5. MemorySynthesizer consumes final behavior for response formatting

### 4.3 Decision Trace

```
Structure:
  decision_trace = {
      "intent": str,
      "changed": bool,
      "before": {...},
      "after": {...},
      "source": "intent" | "global" | "conflict" | "mixed" | "none",
      "confidence": float,
      "confidence_by_dimension": {"tone": float, "depth": float, "style": float},
      "signals": {"intent_strength": float, "global_strength": float, "combined_used": bool},
      "dimensions": {
          "tone": {"source": str, "confidence": float, "changed": bool, ...},
          ...
      }
  }
```

**Flow:**
1. Created by MemoryDecisionTraceLayer at end of BehaviorPipeline
2. Consumed by MemoryConfidenceFeedbackLayer for pattern adjustment
3. Consumed by MemoryPerformanceTracker for success rate tracking

### 4.4 Performance State

```
Structure:
  performance_state = {
      "intent":  {"correct": int, "total": int},
      "global":  {"correct": int, "total": int},
      "conflict": {"correct": int, "total": int}
  }
```

**Flow:**
1. Updated by MemoryPerformanceTracker on each feedback event
2. Consumed by MemoryAdaptiveStrategyLayer for config adjustment
3. Consumed by MemoryStabilityGuardLayer for update gating

### 4.5 Config

```
Structure:
  config = {
      "dominance_threshold": float (1.1-2.0, default 1.5),
      "intent_weight_factor": float (0.1-1.0, default 0.5),
      "global_weight_factor": float (0.1-1.0, default 0.5)
  }
```

**Flow:**
1. Adjusted by MemoryAdaptiveStrategyLayer based on performance_state
2. Gated by MemoryStabilityGuardLayer before application
3. Used by MemoryConflictResolutionLayer (DOMINANCE_THRESHOLD) and MemoryPatternAwareBehaviorLayer

---

## 5. LEARNING LOOP

The complete learning loop follows this sequence:

```
DECISION
  │  BehaviorPipeline.run(intent, behavior, identity)
  │  Returns: final_behavior + decision_trace
  ▼
TRACE
  │  decision_trace captures:
  │    - What changed (before → after per dimension)
  │    - Why (source: intent/global/conflict)
  │    - How confident (top_score / second_score)
  ▼
FEEDBACK
  │  External signal: was the decision correct?
  │  MemoryConfidenceFeedbackLayer.apply(decision_trace, feedback, identity)
  │    - Adjusts weights: +0.2 (intent), +0.15 (conflict), +0.1 (global) ← correct
  │    - Adjusts weights: -0.2 (intent), -0.15 (conflict), -0.1 (global) ← incorrect
  │    - Scales adjustment by confidence (full at confidence ≥ 2.0)
  │    - Soft cap at MAX_WEIGHT = 10.0
  ▼
PATTERN UPDATE
  │  MemoryPatternDecayLayer (0.995 per cycle)
  │  MemoryPatternIntegrator (new signals accumulated)
  ▼
PERFORMANCE TRACKING
  │  MemoryPerformanceTracker.apply(decision_trace, feedback, state)
  │    - Increments total/correct per source
  ▼
STRATEGY UPDATE (gated)
  │  MemoryStabilityGuardLayer (checks MIN_TOTAL=5, STABLE_TOTAL=10, MIN_DELTA=0.05)
  │  MemoryAdaptiveStrategyLayer (adjusts config if guard passes)
  │    - intent accuracy > 0.7 → boost intent_weight_factor +0.1
  │    - global accuracy < 0.5 → penalty global_weight_factor -0.1
  │    - conflict accuracy > 0.8 → reduce dominance_threshold -0.1
  ▼
NEXT DECISION (uses updated identity + config)
```

This loop is **not yet fully automatic** — the feedback signal (`feedback: bool`) is available in the code but is not yet wired into the actual conversation flow. The pipeline exists and works end-to-end in `BehaviorPipeline.run()`, but the feedback loop requires an external caller to provide the feedback signal.

---

## 6. STABILITY MECHANISMS

### 6.1 Soft Caps

| Cap | Value | Location |
|---|---|---|
| Pattern weight MAX | 10.0 | MemoryConfidenceFeedbackLayer.MAX_WEIGHT |
| Verbosity | 1–5 | MemoryAdaptiveBehaviorLayer (min(5, max(1, len))) |
| Importance | 1–10 | MemoryReinforcementLayer (capped at 10) |
| Importance | 1–5 | MemoryManager save_episode (max(1, min(5, importance))) |

### 6.2 Thresholds

| Threshold | Value | Purpose |
|---|---|---|
| Dominance (behavior layer) | 1.5× | PatternAwareBehaviorLayer — how much top must beat second |
| Dominance (conflict layer) | 1.3× | ConflictResolutionLayer — softer for combined signals |
| Dominance adaptive range | 1.1–2.0 | Adjusted by AdaptiveStrategyLayer |
| Score gap (self-correction) | ≥ 2 | MemorySelfCorrectionLayer — prevents unnecessary corrections |
| Fuzzy match (cleaning) | ≥ 0.85 | CleaningOrchestrator — duplicate detection in Notion |
| Memory combine score | ≥ 8 | MemoryCombiner/MemorySynthesizer — minimum relevance threshold |
| Interest extraction | ≥ 8 | MemoryIdentityLayer — minimum score for interest detection |
| Pattern detection | ≥ 7 | MemoryIdentityLayer — minimum score for pattern detection |

### 6.3 Guard Layer (MemoryStabilityGuardLayer)

Three gates must ALL pass for `allow_update = True`:

1. **Minimum data:** Every tracked source (intent, global, conflict) must have `total ≥ 5`
2. **Stability:** Every tracked source must have `total ≥ 10`
3. **Noise gate (bonus):** If `previous_accuracy` exists in config, `|current - previous| ≥ 0.05` for at least one changed source

### 6.4 Confidence Scaling (MemoryConfidenceFeedbackLayer)

```
scale = min(1.0, confidence / 2.0)
adjustment = base_adjustment * scale
```

- At confidence ≥ 2.0 → full adjustment
- At confidence 1.0 → 50% adjustment
- At confidence 0.5 → 25% adjustment

### 6.5 Pattern Decay

```
new_weight = weight * 0.995
if new_weight < 0.05 → prune (remove entry)
```

Applied in MemoryPatternDecayLayer. Ensures old patterns gradually fade if not reinforced.

### 6.6 Input Validation (Defensive Design)

Every layer validates every input:
- Type checks on all fields
- `isinstance` guards for dict, list, str, int, float
- NaN/Inf rejection for float weights
- Empty string rejection
- Negative weight rejection
- `copy.deepcopy` input to prevent mutation
- Default fallbacks for missing keys

---

## 7. CURRENT LIMITATIONS

### Memory System

| Limitation | Detail |
|---|---|
| **No embeddings** | Memory retrieval is heuristic-only (keyword match + scoring). No semantic search. |
| **No vector database** | All memory stored in Notion DBs with title-based filtering. |
| **Inference is hardcoded** | MemoryInference checks only 4 keywords ("agentes", "ia", "ai", "inteligencia"). |
| **Router is rule-based** | MemoryRouter uses exact substring matching on 9 hardcoded phrases. |
| **Decider is rule-based** | MemoryDecider uses 4 explicit keywords + 6 high-value patterns. |
| **No memory consolidation** | No cross-session pattern extraction. Short/medium/long tiers exist but long-term is Notion-only. |
| **Self-correction is best-effort** | Deprecation is no-op in v1 (only logs). |
| **Feedback not wired** | The feedback loop (ConfidenceFeedbackLayer → PerformanceTracker → AdaptiveStrategy) requires manual integration. No automated feedback from AI responses. |

### Behavior Pipeline

| Limitation | Detail |
|---|---|
| **No real-time adaptation** | Pattern updates via feedback require explicit `feedback=True/False` calls. |
| **Stability guard is one-directional** | Only blocks updates. No mechanism to accelerate learning when data is abundant. |
| **Only 3 dimensions** | Tone, depth, style — no support for custom dimensions. |
| **No AI in pipeline** | By design, but this means no semantic understanding of patterns. |
| **Patterns are identity-scoped** | No cross-user pattern learning or global model. |

### Architecture

| Limitation | Detail |
|---|---|
| **Dual Notion implementations** | Two incompatible implementations (sync SDK in `services/`, async httpx in `core/`). |
| **God file (legacy)** | `app/services/telegram_service.py` ~1394 lines with 13 responsibilities (still imported by `nexus_bot.py`). |
| **Circular dependency** | `NotionCleanerAgent` imports `call_ai_with_fallback` from `telegram_service.py`, which has `NotionCleanerAgent` imported transitively. |
| **Zombie agents** | `agents/planner.py`, `executor.py`, `blueprint.py` are placeholders. |
| **Self-API call** | Bot calls own `build-app` endpoint via HTTP loopback instead of direct invocation. |
| **RAM-only state** | `user_states` in `app/main.py` is not persisted. Restart loses all in-progress conversations. |
| **No authentication** | Endpoints are open (no API key validation on webhook, etc.). |
| **No rate limiting** | No protection against abuse from Telegram (rapid messages). |
| **No logging persistence** | Logs are stdout-only. No file rotation, no structured logging. |

### Production Readiness

| Limitation | Detail |
|---|---|
| **No unit tests for pipeline** | All tests are integration tests (`test_*.py`). Pipeline layers are designed for unit testability but not tested. |
| **No concurrency handling** | Global `chat_states` and `current_api_index` are not thread-safe. |
| **No health checks on Notion** | Notion availability is assumed. Failures surface as user errors. |
| **No retry backoff** | API cascade retries immediately with next provider on any error. No exponential backoff. |

---

## 8. READINESS ASSESSMENT

### Stability: ✅ MODERATE

- **Input validation:** Excellent — every layer performs thorough type checking with defensive defaults
- **No side effects:** All pipeline layers use `copy.deepcopy` to prevent input mutation
- **Determinism:** All layers are pure functions (same input → same output). No randomness, no timestamps, no real-time logic.
- **Exception safety:** All external calls (Notion, AI, backend) are wrapped in try/except with graceful fallbacks
- **Weakness:** Global state (`current_api_index`, `chat_states`) is mutable and shared. No locks.

### Determinism: ✅ FULL (Pipeline)

The behavior decision pipeline (`BehaviorPipeline` and all its layers) is **fully deterministic**:
- No AI calls
- No randomness
- No timestamps
- No real-time signals
- Same inputs → same outputs across all runs
- All numeric operations use deterministic math (sort, sum, max, min)

The memory retrieval pipeline is **deterministic per query** (same memories + same query → same result) but memories in Notion can change over time.

### Production-Ready (Internally): ⚠️ CONDITIONAL

**What works:**
- ✅ Multi-API cascade with fallback — production-grade
- ✅ Notion integration — robust error handling, ID cleaning, retry
- ✅ Behavior decision pipeline — fully implemented, deterministic, well-tested architecture
- ✅ System prompt and function calling — well-designed, includes safety instructions

**What's missing for production:**
- ❌ No persistence for `user_states` (RAM-only)
- ❌ No authentication on endpoints
- ❌ No rate limiting
- ❌ No concurrency protection
- ❌ Dual Notion implementations will cause asymmetric bugs
- ❌ No unit tests for the pipeline (all test files are integration-level)
- ❌ Feedback loop not wired — the learning pipeline exists but is idle
- ❌ Legacy `telegram_service.py` still imported by `nexus_bot.py`

**Verdict:** The behavior decision system is production-ready in isolation. The overall application is **pre-production** — functional for single-user use, but would need hardening for multi-user production deployment.
