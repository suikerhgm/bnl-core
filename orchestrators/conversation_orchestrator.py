"""
Orquestador de conversación del bot NexusAgentes.
Contiene la lógica de conversación principal (process_message).
Integra recuperación de memoria contextual antes de llamar a la IA.
"""
import json
import logging
from typing import Dict, List, Optional, Any

from core.state_manager import save_states
from core.ai_cascade import (
    call_ai_with_fallback,
    NEXUS_BNL_SYSTEM_PROMPT
)
from core.notion_gateway import (
    notion_search,
    notion_fetch,
    notion_create
)
from core.backend_client import call_build_app, call_execute_plan
from core.formatters import (
    _format_plan_result,
    _format_execution_result,
    build_memory_context,
)
from core.tools import NOTION_TOOLS
from core.memory_manager import MemoryManager
from core.memory_router import MemoryRouter
from core.memory_response_layer import MemoryResponseLayer
from core.memory_selector import MemorySelector
from core.memory_combiner import MemoryCombiner
from core.memory_synthesizer import MemorySynthesizer
from core.memory_deduplicator import MemoryDeduplicator
from core.memory_conflict_resolver import MemoryConflictResolver
from core.memory_inference import MemoryInference
from core.memory_evolution import MemoryEvolution
from core.memory_self_correction import MemorySelfCorrectionLayer
from core.memory_reinforcement import MemoryReinforcementLayer
from core.memory_identity import MemoryIdentityLayer
from core.memory_decision import MemoryDecisionLayer
# ── Behavior Pipeline (replaces MemoryAdaptiveBehaviorLayer) ────────
from core.behavior_pipeline import BehaviorPipeline
# ── Pattern extraction & integration ───────────────────────────────
from core.memory_pattern_signal_extractor import MemoryPatternSignalExtractor
from core.memory_pattern_integrator import MemoryPatternIntegrator
# ── Feedback Loop components ────────────────────────────────────────
from core.memory_confidence_feedback_layer import MemoryConfidenceFeedbackLayer
from core.memory_performance_tracker import MemoryPerformanceTracker
from core.memory_stability_guard_layer import MemoryStabilityGuardLayer
from core.memory_adaptive_strategy_layer import MemoryAdaptiveStrategyLayer
# ── Persistencia del learning loop ───────────────────────────────────
from core.persistence import (
    load_identity as load_persisted_identity,
    save_identity as save_persisted_identity,
    load_performance as load_persisted_performance,
    save_performance as save_persisted_performance,
    load_config as load_persisted_config,
    save_config as save_persisted_config,
)



logger = logging.getLogger(__name__)

# ── Singletons ──────────────────────────────────────────────────────
_memory_manager = MemoryManager()
_memory_router = MemoryRouter()
_memory_response = MemoryResponseLayer()
_memory_selector = MemorySelector()

# ── Behavior pipeline (singleton) ───────────────────────────────────
_behavior_pipeline = BehaviorPipeline()

# ── Pattern extractor & integrator (singletons) ────────────────────
_pattern_extractor = MemoryPatternSignalExtractor()
_pattern_integrator = MemoryPatternIntegrator()

# ── Feedback loop components (singletons) ───────────────────────────
_confidence_feedback = MemoryConfidenceFeedbackLayer()
_performance_tracker = MemoryPerformanceTracker()
_stability_guard = MemoryStabilityGuardLayer()
_adaptive_strategy = MemoryAdaptiveStrategyLayer()

# ── Feedback keyword detection ──────────────────────────────────────
# Negative feedback → False (criticism / correction)
_NEGATIVE_KEYWORDS = [
    "mal", "incorrecto", "eso está mal", "no era eso",
    "equivocado", "wrong", "incorrect",
]
# Positive feedback → True (approval)
_POSITIVE_KEYWORDS = [
    "bien", "correcto", "perfecto", "asi esta bien",
]
# Preference signals → None (pattern learning, no feedback penalty)
_PREFERENCE_KEYWORDS = [
    "más técnico", "más formal", "más corto", "más directo",
    "menos técnico", "menos formal", "menos casual",
]

# ── Caché de memoria en RAM (corto plazo) ──────────────────────────
_recent_memory: dict = {}
MAX_MEMORIES = 10


def _detect_feedback(user_message: str) -> Optional[bool]:
    """Detecta feedback del usuario.
    
    Retorna:
        True  → feedback positivo (aprobación explícita)
        False → feedback negativo (crítica / corrección)
        None  → mensaje neutro o señal de preferencia (sin feedback)
    """
    msg = user_message.lower().strip()

    # Preference signals → None (no feedback penalty, solo pattern learning)
    for kw in _PREFERENCE_KEYWORDS:
        if kw in msg:
            logger.debug("🧠 Preference signal detected: '%s' → feedback=None", kw)
            return None

    # Negative feedback → False
    for kw in _NEGATIVE_KEYWORDS:
        if kw in msg:
            logger.info("🧠 Negative feedback detected: '%s' → feedback=False", kw)
            return False

    # Positive feedback → True
    for kw in _POSITIVE_KEYWORDS:
        if kw in msg:
            logger.info("🧠 Positive feedback detected: '%s' → feedback=True", kw)
            return True

    # Default: neutro → None
    return None


def _run_feedback_loop(
    decision_trace: Dict[str, Any],
    feedback: bool,
    identity: Dict[str, Any],
    performance_state: Dict[str, Any],
    config: Dict[str, Any],
) -> None:
    """
    Ejecuta el feedback loop completo sobre los objetos mutables.
    Todos los fallos son silenciosos (solo log).
    """
    try:
        logger.info("🔥 FEEDBACK LOOP EXECUTED")
        # 1. Adjust identity patterns based on feedback
        fb_result = _confidence_feedback.apply({
            "decision_trace": decision_trace,
            "feedback": feedback,
            "identity": identity,
        })
        fb_identity = fb_result.get("identity")
        if isinstance(fb_identity, dict):
            identity.clear()
            identity.update(fb_identity)

        # 2. Update performance counters
        perf_result = _performance_tracker.apply({
            "decision_trace": decision_trace,
            "feedback": feedback,
            "state": performance_state,
        })
        perf_state = perf_result.get("state")
        if isinstance(perf_state, dict):
            performance_state.clear()
            performance_state.update(perf_state)

        # 3. Check stability guard before strategy update
        guard_result = _stability_guard.apply({
            "performance_state": performance_state,
            "config": config,
        })
        allow_update = guard_result.get("allow_update", False)

        # 4. Update strategy only if guard allows
        if allow_update:
            strategy_result = _adaptive_strategy.apply({
                "performance_state": performance_state,
                "config": config,
            })
            strategy_config = strategy_result.get("config")
            if isinstance(strategy_config, dict):
                config.clear()
                config.update(strategy_config)

        logger.info(
            "🧠 Feedback loop: feedback=%s source=%s changed=%s guard=%s",
            feedback,
            decision_trace.get("source", "?"),
            decision_trace.get("changed", False),
            allow_update,
        )
    except Exception as e:
        logger.warning("⚠️ Feedback loop error: %s", e, exc_info=True)


def _persist_learning_state(user_id: str, identity: dict, perf: dict, cfg: dict) -> None:
    """Guarda el estado del learning loop. Fallo silencioso."""
    try:
        save_persisted_identity(user_id, identity)
        save_persisted_performance(user_id, perf)
        save_persisted_config(user_id, cfg)
        logger.debug("🔁 Persisted state for user '%s'", user_id)
    except Exception as e:
        logger.warning("⚠️ Failed to persist learning loop state: %s", e)


def _build_memory_response(memories, user_message):
    ranked = _memory_selector.rank(memories, user_message)
    combined = MemoryCombiner.combine(ranked)
    if combined:
        return combined
    mem = _memory_selector.select(memories, user_message)
    if mem:
        return _memory_response.generate(mem)
    return None


# ===== LÓGICA PRINCIPAL DEL BOT (con learning loop completo) =====


async def process_message(user_message: str, chat_id: int, state: Dict) -> str:
    """
    Procesa un mensaje del usuario con el learning loop completo:

    1. LOAD — carga identidad, rendimiento y configuración desde SQLite
    2. PROCESS — ejecuta la lógica de conversación
    3. FEEDBACK — aplica el feedback loop si hubo decisión de comportamiento
    4. SAVE — persiste todo el estado actualizado
    """
    # ═══════════════════════════════════════════════════════════════
    # STEP 1 — LOAD persisted learning loop state
    # ═══════════════════════════════════════════════════════════════
    user_id = str(chat_id)
    persisted_identity = load_persisted_identity(user_id)
    performance_state = load_persisted_performance(user_id)
    config = load_persisted_config(user_id)
    logger.info(
        "🔁 Loaded state for user '%s': "
        "patterns=%d perf={intent:%d global:%d conflict:%d} threshold=%.1f",
        user_id,
        len(persisted_identity.get("patterns", {})),
        performance_state.get("intent", {}).get("total", 0),
        performance_state.get("global", {}).get("total", 0),
        performance_state.get("conflict", {}).get("total", 0),
        config.get("dominance_threshold", 1.5),
    )

    # Contenedor mutable para recibir el decision_trace desde _process_message_inner
    _decision_trace_container: List[Dict[str, Any]] = []

    # ═══════════════════════════════════════════════════════════════
    # STEP 2 — Process the message
    # ═══════════════════════════════════════════════════════════════
    result = await _process_message_inner(
        user_message, chat_id, state,
        persisted_identity, performance_state, config,
        _decision_trace_container,
    )

    # ═══════════════════════════════════════════════════════════════
    # STEP 3 — FEEDBACK LOOP (if a behavior decision was made)
    # ═══════════════════════════════════════════════════════════════
    if _decision_trace_container:
        decision_trace = _decision_trace_container[0]
        feedback = _detect_feedback(user_message)

        logger.info("🧠 Decision Trace: %s", decision_trace)

        if feedback is not None:
            logger.info("📊 Performance (before): %s", performance_state)
            logger.info("⚙️ Config (before): %s", config)

            _run_feedback_loop(
                decision_trace, feedback,
                persisted_identity, performance_state, config,
            )

            logger.info("📊 Performance (after): %s", performance_state)
            logger.info("⚙️ Config (after): %s", config)
        else:
            logger.debug("🧠 Feedback is None — skipping feedback loop, pattern learning only")
    else:
        logger.debug("🧠 No behavior decision in this interaction — skipping feedback loop")

    # ═══════════════════════════════════════════════════════════════
    # STEP 4 — SAVE persisted learning loop state
    # ═══════════════════════════════════════════════════════════════
    _persist_learning_state(user_id, persisted_identity, performance_state, config)

    return result


async def _process_message_inner(
    user_message: str,
    chat_id: int,
    state: Dict,
    persisted_identity: Dict[str, Any],
    persisted_performance: Dict[str, Any],
    persisted_config: Dict[str, Any],
    decision_trace_container: List[Dict[str, Any]],
) -> str:
    """
    Lógica interna de procesamiento de mensajes.

    Si se ejecuta el BehaviorPipeline, el decision_trace se almacena en
    decision_trace_container para que el caller (process_message) pueda
    ejecutar el feedback loop.
    """
    import os
    logger.info(f"🚨 RUNNING FILE: {__file__}")
    logger.info("🚨 NEW FLOW ACTIVE")

    logger.info(f"STATE {chat_id}: {state}")

    chat_id_str = str(chat_id)
    user_lower = user_message.lower().strip()

    # ═══════════════════════════════════════════════════════════════
    # 1. DIRECT MEMORY CAPTURE (antes de cualquier AI o tool)
    # ═══════════════════════════════════════════════════════════════
    if "recuerda" in user_lower or "remember" in user_lower:
        logger.info("🧠 Direct memory capture triggered")

        summary = user_message[:100]

        # Detectar key y value dinámicamente
        temp_layer = MemoryResponseLayer()
        detected = temp_layer._extract_fields({"summary": user_message})

        if detected:
            key = detected["key"]
            value = detected["value"]
        else:
            key = "general"
            value = MemoryResponseLayer._extract_clean_value(user_message)

        # Fallback extra de seguridad
        if not value or value.lower() == user_message.lower():
            value = user_message.replace("Recuerda esto:", "").replace("Remember:", "").strip()

        memory = {
            "type": "fact",
            "key": key,
            "value": value,
            "content": user_message,
            "summary": summary,
            "tags": [key],
            "importance": 5,
        }

        try:
            await _memory_manager.save_episode(
                content=memory["content"],
                summary=memory["summary"],
                tags=memory["tags"],
                importance=memory["importance"],
            )
            if chat_id_str not in _recent_memory:
                _recent_memory[chat_id_str] = []
            _recent_memory[chat_id_str].append(memory)
            if len(_recent_memory[chat_id_str]) > MAX_MEMORIES:
                _recent_memory[chat_id_str] = _recent_memory[chat_id_str][-MAX_MEMORIES:]
            return f"🧠 Guardado: {summary}"
        except Exception as e:
            logger.warning(f"Memory storage failed: {e}")

    # ── Fallback simple para preguntas directas de memoria ──────────
    simple_queries = [
        "como me llamo",
        "cómo me llamo",
        "mi nombre",
        "como se llama mi proyecto",
        "cómo se llama mi proyecto",
        "que te dije",
        "qué te dije",
    ]

    if chat_id_str in _recent_memory and any(q in user_lower for q in simple_queries):
        logger.info("🧠 Simple memory fallback triggered")
        memories = _recent_memory[chat_id_str]
        response = _build_memory_response(memories, user_message)
        if response:
            return response

    # ═══════════════════════════════════════════════════════════════
    # 2. MEMORY ROUTER (responder desde RAM si aplica)
    # ═══════════════════════════════════════════════════════════════
    if _memory_router.should_use_memory(user_message):
        if chat_id_str in _recent_memory:
            memories = _recent_memory[chat_id_str]
            response = _build_memory_response(memories, user_message)
            if response:
                logger.info("🧠 MemoryRouter: responding from RAM")
                return response

        logger.info("🧠 MemoryRouter: no memory found, fallback to AI")

    # ── Synthesizer para consultas complejas de perfil ──────────────
    complex_queries = [
        "que sabes", "qué sabes", "perfil", "sobre mi", "sobre mí"
    ]

    if chat_id_str in _recent_memory and any(q in user_lower for q in complex_queries):
        memories = _recent_memory[chat_id_str]

        if len(memories) == 1:
            memory = memories[0]
            response = MemoryResponseLayer.generate(memory)
            if response:
                return response

        ranked = _memory_selector.rank(memories, user_message)

        cleaned = MemoryDeduplicator.deduplicate(ranked)
        resolved = MemoryConflictResolver.resolve(cleaned)
        evolved = MemoryEvolution.evolve(resolved)
        inferred = MemoryInference.infer(evolved)
        await MemorySelfCorrectionLayer.correct(inferred, _memory_manager)
        await MemoryReinforcementLayer.reinforce(inferred, _memory_manager)

        identity = MemoryIdentityLayer.build_identity(inferred)
        logger.info("🧠 Identity built: %s", identity)

        # ── Merge persisted patterns into local identity ─────────────
        if persisted_identity.get("patterns"):
            persisted_pattern_keys = list(persisted_identity["patterns"].keys())
            identity.setdefault("patterns", [])
            for key in persisted_pattern_keys:
                if key not in identity["patterns"]:
                    identity["patterns"].append(key)

        # ── Intent calculado UNA vez y reutilizado ─────────────────
        decision_layer = MemoryDecisionLayer()
        intent = decision_layer.detect_intent(user_message.lower().strip())

        decided = MemoryDecisionLayer.decide(inferred, identity, user_message, intent=intent)
        logger.info("🧠 Decision layer: %d memories selected", len(decided))

        # ═══════════════════════════════════════════════════════════════
        # BEHAVIOR PIPELINE — Reemplaza MemoryAdaptiveBehaviorLayer
        # ═══════════════════════════════════════════════════════════════
        # Base behavior from the adaptive layer (non-pattern logic)
        from core.memory_adaptive_behavior_layer import MemoryAdaptiveBehaviorLayer
        _adaptive_fallback = MemoryAdaptiveBehaviorLayer()
        behavior_base = _adaptive_fallback.apply(decided, identity, user_message, intent)

        # Run the full BehaviorPipeline
        bp_result = _behavior_pipeline.run(
            intent=intent,
            behavior=behavior_base,
            identity=persisted_identity,
        )
        behavior = bp_result["behavior"]
        decision_trace = bp_result["decision_trace"]

        logger.info("DEBUG decision_trace: %s", decision_trace)

        # Store decision_trace for the feedback loop in process_message
        decision_trace_container.append(decision_trace)

        logger.info("🧠 BehaviorPipeline result: %s", behavior)
        logger.info("🧠 Decision trace: changed=%s source=%s confidence=%.2f",
                     decision_trace.get("changed"),
                     decision_trace.get("source"),
                     decision_trace.get("confidence", 0.0))

        synthesized = MemorySynthesizer.synthesize(decided, identity, behavior)

        if synthesized:
            return synthesized

    # ═══════════════════════════════════════════════════════════════
    # 3. NORMAL FLOW — comandos directos, AI, tools
    # ═══════════════════════════════════════════════════════════════

    # ── Detectar intención de organizar Notion ────────────
    if "organiza" in user_lower or "limpia" in user_lower:
        state["state"] = "NOTION_CLEANING"
        state["mode"] = "searching"
        save_states()
        return "🧠 Analizando Notion... ¿Qué carpeta quieres organizar?"

    if state.get("state") == "WAITING_CONFIRMATION":
        if user_lower in ["si", "sí", "yes", "dale"]:
            plan_id = state.get("plan_id")
            result = await call_execute_plan(plan_id)
            state["state"] = "EXECUTING"
            save_states()
            return _format_execution_result(result)

        elif user_lower in ["no", "cancelar"]:
            state["state"] = "IDLE"
            save_states()
            return "❌ Cancelado. ¿Qué quieres hacer ahora?"

    # ── Manejar flujo de limpieza de Notion ─────────────────
    from orchestrators.cleaning_orchestrator import handle_cleaning_flow
    response = await handle_cleaning_flow(user_message, chat_id, state)
    if response:
        return response

    # ── Detectar comandos directos ──────────────────────────
    if user_lower.startswith("ejecutar "):
        plan_id = user_message[len("ejecutar "):].strip()
        if plan_id:
            logger.info(f"⚡ Comando directo: ejecutar plan '{plan_id}'")
            result = await call_execute_plan(plan_id)
            if "error" in result:
                return f"⚠️ Error al ejecutar plan:\n{result['error']}"
            return _format_execution_result(result)

    if user_lower.startswith(("plan ", "build ", "crea ", "construye ")):
        for prefix in ("plan ", "build ", "crea ", "construye "):
            if user_lower.startswith(prefix):
                idea = user_message[len(prefix):].strip()
                break
        if idea:
            logger.info(f"🔨 Comando directo: build_app con idea '{idea}'")
            result = await call_build_app(idea)
            if "error" in result:
                return f"⚠️ Error al generar plan:\n{result['error']}"
            state["state"] = "WAITING_CONFIRMATION"
            state["plan_id"] = result.get("plan_id")
            save_states()
            return _format_plan_result(result)

    # ── Recuperar memoria relevante para contexto ───────────
    try:
        memories = await _memory_manager.retrieve(user_message, k=3)
    except Exception as e:
        logger.warning("⚠️ Fallo en recuperación de memoria: %s", e)
        memories = []

    # ── Build memory context for AI prompt ───────────────────
    try:
        memory_context = build_memory_context(memories)
    except Exception as e:
        logger.warning("⚠️ Fallo al construir contexto de memoria: %s", e)
        memory_context = ""

    memory_instruction = (
        "[IMPORTANT INSTRUCTIONS]\n\n"
        "You have access to MEMORY CONTEXT.\n\n"
        "1. ALWAYS use memory context FIRST if relevant\n"
        "2. If the answer is in memory, DO NOT call any tools\n"
        "3. Only use tools if memory does not contain the answer\n"
        "4. Memory is more reliable than external sources\n\n"
        "[END INSTRUCTIONS]\n"
    )

    if memory_context:
        user_prompt = f"{memory_instruction}\n{memory_context}\n\nUSER:\n{user_message}"
        logger.info("🧠 Memoria contextual inyectada (%d caracteres)", len(memory_context))
    else:
        user_prompt = f"{memory_instruction}\nUSER:\n{user_message}"

    # ═══════════════════════════════════════════════════════════════
    # AI LOOP — sin lógica de memoria dentro
    # ═══════════════════════════════════════════════════════════════
    messages = [
        {"role": "system", "content": NEXUS_BNL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    max_iterations = 5
    for iteration in range(max_iterations):
        logger.info(f"🔄 Iteración {iteration + 1}")

        try:
            response, api_used = await call_ai_with_fallback(messages, tools=NOTION_TOOLS)
            content = response["content"]
            raw = response["raw"]
            assistant_message = raw.choices[0].message

            logger.info(f"🤖 AI RESPONSE: {content[:200]}")
            logger.info(f"🧠 Provider: {response.get('provider')}")

            if not hasattr(assistant_message, 'tool_calls') or not assistant_message.tool_calls:

                # ── Extract pattern signals from user message ──
                try:
                    from core.memory_decision import MemoryDecisionLayer
                    decision_layer = MemoryDecisionLayer()

                    intent = decision_layer.detect_intent(user_message.lower().strip())

                    extract_result = _pattern_extractor.extract({
                        "message": user_message,
                        "intent": intent,
                        "behavior": {}
                    })

                    pattern_signals = extract_result.get("pattern_signals", [])

                    if pattern_signals:
                        logger.info("🧠 Pattern signals detected: %s", pattern_signals)

                        integrate_result = _pattern_integrator.integrate({
                            "pattern_signals": pattern_signals,
                            "identity": persisted_identity
                        })

                        persisted_identity = integrate_result["identity"]

                except Exception as e:
                    logger.warning("⚠️ Pattern extraction failed: %s", e)

                # ── RUN BehaviorPipeline for ALL messages ──
                try:
                    from core.memory_decision import MemoryDecisionLayer
                    decision_layer = MemoryDecisionLayer()

                    intent = decision_layer.detect_intent(user_message.lower().strip())

                    # Minimal base behavior
                    behavior_base = {
                        "tone": "neutral",
                        "depth": "medium",
                        "style": "concise",
                        "verbosity": 3
                    }

                    bp_result = _behavior_pipeline.run(
                        intent=intent,
                        behavior=behavior_base,
                        identity=persisted_identity,
                    )

                    decision_trace = bp_result["decision_trace"]

                    logger.info("DEBUG (fallback) decision_trace: %s", decision_trace)

                    decision_trace_container.append(decision_trace)

                except Exception as e:
                    logger.warning("⚠️ BehaviorPipeline fallback failed: %s", e)

                return content or "Sin respuesta"

            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in assistant_message.tool_calls
                ]
            })

            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                logger.info(f"🔧 Ejecutando: {function_name} con {function_args}")

                if function_name == "notion_search":
                    result = await notion_search(function_args["query"])
                elif function_name == "notion_fetch":
                    result = await notion_fetch(function_args["page_id"])
                elif function_name == "notion_create":
                    old_properties = {
                        "title": {"title": [{"text": {"content": function_args.get("title", "")}}]}
                    }
                    old_children = [{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": function_args.get("content", "")}}]
                        }
                    }]
                    result = await notion_create(
                        function_args.get("parent_id", ""),
                        old_properties,
                        old_children
                    )
                elif function_name == "build_app":
                    result = await call_build_app(function_args["idea"])
                elif function_name == "execute_plan":
                    result = await call_execute_plan(function_args["plan_id"])
                else:
                    result = {"error": f"Función desconocida: {function_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })

        except Exception as e:
            logger.error(f"❌ Error en iteración {iteration + 1}: {str(e)}", exc_info=True)
            return f"⚠️ Error: {str(e)}"

    return "⚠️ Alcancé el límite de iteraciones. Por favor, reformula tu pregunta."
