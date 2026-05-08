"""
Motor de ejecución central de NexusAgentes.
Contiene toda la lógica de intent detection, action routing, execution y result handling.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import httpx

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
from core.tools import NOTION_TOOLS, FILESYSTEM_TOOLS
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
# ── Action System (Fase 2) ──────────────────────────────────────────
from core.action_router import ActionRouter
from core.action_logger import ActionLogger
from core.approval_system import ApprovalSystem
from core.actions.file_action import FileAction
from core.agents.planner_agent import PlannerAgent
from core.agents.agent_registry import registry as _agent_registry
from core.actions.code_action import CodeAction
from core.actions.backend_action import BackendAction
from core.actions.command_action import CommandAction, get_run_command
from core.validation_layer import ValidationLayer
from core.runtime.port_allocator import find_free_port
import core.agents  # triggers registry.register() calls
import time


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

# ── El Forjador: explicit build approval tokens ─────────────────────
# Only EXACT whole-message matches count as approval.
# Partial matches (substring, prefix) are intentionally excluded to
# prevent "¿cómo construir esto?" or "ejecuta eso" from triggering a build.
_EXPLICIT_APPROVAL_TOKENS = frozenset([
    "aprobado", "approved",
    "si", "sí", "yes",
    "ok", "dale", "hazlo",
])


def _is_explicit_approval(msg: str) -> bool:
    """
    Return True ONLY when the entire trimmed message is an unambiguous
    confirmation token.  Questions, sentences, and new code requests
    never match — even if they contain an approval word as a substring.
    """
    return msg.strip().lower() in _EXPLICIT_APPROVAL_TOKENS


def _wants_auto_approve(msg: str) -> bool:
    """Return True if the message/spec contains auto_aprobar: true (Bug #3 fix)."""
    low = msg.lower()
    return "auto_aprobar: true" in low or "auto_aprobar:true" in low


# ── Caché de memoria en RAM (corto plazo) ──────────────────────────
_recent_memory: dict = {}
MAX_MEMORIES = 10

# ── Active app context (Bug #5 fix) ────────────────────────────────
# Updated whenever a project is auto-run so subsequent requests can
# interact with it without regenerating code.
_active_app: dict = {}  # keys: project_id, port, path


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


# ═══════════════════════════════════════════════════════════════════
# ACTION SYSTEM — Helpers para ejecución de acciones
# ═══════════════════════════════════════════════════════════════════

def _should_execute_action(intent: str) -> bool:
    """
    Determina si un intent del BehaviorPipeline debe disparar una acción.

    Args:
        intent: Intención detectada (notion_create, file_read, etc.)

    Returns:
        True si hay una acción mapeada para este intent
    """
    if not intent:
        return False
    return intent in ActionRouter.INTENT_ACTION_MAP


async def _execute_action(
    intent: str,
    decision_trace: Dict[str, Any],
    user_message: str,
    chat_id: int,
    extra_params: Optional[Dict[str, Any]] = None,
    _is_retry: bool = False,
) -> Optional[str]:
    """
    Ejecuta el Action System completo para un intent dado.

    Flujo:
        1. Route: convertir intent → instancia de BaseAction
        2. Approve: si requiere aprobación, pedir vía Telegram
        3. Execute: ejecutar la acción
        3b. Persist: si CodeAction build mode, escribir archivos a disco
        4. Log: persistir resultado en SQLite
        5. Format: retornar mensaje legible para el usuario

    Args:
        intent: Intención detectada (notion_create, etc.)
        decision_trace: Traza de decisión del BehaviorPipeline
        user_message: Mensaje original del usuario
        chat_id: ID del chat de Telegram
        extra_params: Parámetros adicionales inyectados por el caller (ej. mode)

    Returns:
        String con mensaje de resultado para el usuario, o None si no hay acción
    """
    user_id = str(chat_id)

    # Extraer parámetros del mensaje del usuario
    params = _extract_action_params(intent, user_message)
    if extra_params:
        params.update(extra_params)

    # 1. Route
    action_context = {
        "user_id": user_id,
        "params": {
            **params,
            # Guarantee the raw user message is always reachable as "request"
            "request": params.get("request") or user_message,
        },
        "user_message": user_message,
        "decision_trace": decision_trace,
    }

    action = ActionRouter.route(decision_trace, intent, action_context)
    if action is None:
        logger.info(f"⏭️ No action to execute for intent: {intent}")
        return None

    logger.info(f"⚡ Action routed: {action.action_type} ({action.get_description()})")

    # 2. Approve (if needed)
    approved: Optional[bool] = None
    if action.requires_approval():
        telegram_chat_id = chat_id  # El chat_id del usuario es su chat_id de Telegram
        logger.info(f"🔒 Action requires approval, requesting from chat {telegram_chat_id}")
        approved = await ApprovalSystem.request_approval(action, telegram_chat_id)

        if approved is False:
            logger.info("❌ Action rejected by user")
            # Log the rejection
            ActionLogger.log(
                user_id=user_id,
                action_type=action.action_type,
                params=params,
                result={"success": False, "error": "Rejected by user"},
                approved=False,
                duration_ms=0,
            )
            return f"❌ Acción rechazada por el usuario: {action.get_description()}"
        elif approved is None:
            logger.warning("⏰ Approval timeout or error")
            ActionLogger.log(
                user_id=user_id,
                action_type=action.action_type,
                params=params,
                result={"success": False, "error": "Approval timeout"},
                approved=None,
                duration_ms=0,
            )
            return f"⏰ Tiempo de espera agotado para la acción: {action.get_description()}"

    # 3. Execute
    logger.info(f"🚀 Executing action: {action.action_type}")
    start_time = time.time()

    try:
        result = await action.execute()
    except Exception as e:
        logger.error(f"❌ Action execution failed: {e}", exc_info=True)
        result = {"success": False, "result": None, "error": str(e)}

    duration_ms = int((time.time() - start_time) * 1000)

    # 3b. Persist multi-file CodeAction output to disk (build mode only)
    if (
        action.action_type == "CodeAction"
        and result.get("success")
        and isinstance(result.get("result"), dict)
        and "files" in result["result"]
        and result["result"].get("mode") != "blueprint"
    ):
        file_action = FileAction({
            "operation": "write_project",
            "params": {"files": result["result"]["files"]},
        })
        try:
            write_result = await file_action.execute()
            inner = write_result.get("result") or {}
            if write_result.get("success") and inner.get("project_path"):
                result["_project_path"] = inner["project_path"]
                result["_files_written"] = inner.get("files_written", len(result["result"]["files"]))
                logger.info(
                    "💾 El Forjador: project saved → %s (%d file(s))",
                    inner["project_path"],
                    result["_files_written"],
                )
                # Git checkpoint immediately after write (best-effort)
                try:
                    from core.git_manager import checkpoint as _git_checkpoint
                    _git_checkpoint(
                        Path(inner["project_path"]),
                        "[AI] generated app",
                    )
                except Exception as _ge:
                    logger.warning("⚠️ Git checkpoint failed: %s", _ge)

                # Auto-run: allocate a free port and detect the start command
                _auto_port = find_free_port()
                _run_cmd = get_run_command(inner["project_path"], result["result"]["files"], port=_auto_port)
                if _run_cmd:
                    # Mark as known before awaiting so RE's scan skips a duplicate launch
                    _auto_pid = Path(inner["project_path"]).name
                    try:
                        from core.runtime.runtime_engine import get_engine as _get_engine_pre
                        _get_engine_pre()._known.add(_auto_pid)
                    except Exception:
                        pass
                    _cmd_action = CommandAction({
                        "operation": "run",
                        "params": {
                            "command": _run_cmd,
                            "cwd": inner["project_path"],
                            "project_id": _auto_pid,
                        },
                    })
                    try:
                        _run_result = await _cmd_action.execute()
                        result["_run_result"] = _run_result
                        logger.info(
                            "🚀 Auto-run: '%s' → returncode=%s timed_out=%s",
                            _run_cmd,
                            _run_result.get("result", {}).get("returncode"),
                            _run_result.get("result", {}).get("timed_out"),
                        )
                        # Bug #5 fix: track active app so follow-up requests
                        # can interact with it instead of generating new code.
                        if _run_result.get("success"):
                            _active_app.update({
                                "project_id": Path(inner["project_path"]).name,
                                "port": _auto_port,
                                "path": inner["project_path"],
                            })
                            logger.info(
                                "📍 Active app set: %s on port %s",
                                _active_app["project_id"], _auto_port,
                            )
                        # Bug #6 fix: minimal startup test — wait then GET /ping
                        if _run_result.get("success"):
                            await asyncio.sleep(2.0)
                            try:
                                async with httpx.AsyncClient(timeout=4.0) as _hc:
                                    _ping = await _hc.get(
                                        f"http://127.0.0.1:{_auto_port}/ping"
                                    )
                                    result["_auto_test"] = {
                                        "status": _ping.status_code,
                                        "response": _ping.text[:300],
                                    }
                                    logger.info(
                                        "🧪 Auto-test /ping → %s %s",
                                        _ping.status_code, _ping.text[:80],
                                    )
                            except Exception as _te:
                                result["_auto_test"] = {"error": str(_te)}
                                logger.warning("⚠️ Auto-test failed: %s", _te)
                        # Schedule repair loop — catches crashes that happen after
                        # the 500ms startup window (e.g. missing imports surfaced
                        # when the first request arrives or psutil not installed).
                        try:
                            from core.runtime.runtime_engine import get_engine as _get_engine
                            asyncio.create_task(
                                _get_engine()._repair_loop(
                                    _auto_pid,
                                    Path(inner["project_path"]),
                                )
                            )
                            logger.info("🔧 Repair loop scheduled for '%s'", _auto_pid)
                        except Exception as _re_exc:
                            logger.warning("⚠️ Could not schedule repair loop: %s", _re_exc)
                    except Exception as _exc:
                        logger.warning("⚠️ Auto-run failed: %s", _exc)
            else:
                logger.warning("⚠️ FileAction.write_project failed: %s", inner.get("error"))
        except Exception as exc:
            logger.warning("⚠️ Could not persist project to disk: %s", exc)

    # 3c. ValidationLayer — verify build completeness (single retry if incomplete)
    _validation_prefix: Optional[str] = None
    if (
        not _is_retry
        and action.action_type == "CodeAction"
        and result.get("success")
        and isinstance(result.get("result"), dict)
        and result["result"].get("mode") != "blueprint"
        and "files" in result["result"]
    ):
        _vl = ValidationLayer()
        _validation = _vl.validate(user_message, result["result"])
        if not _validation["is_valid"]:
            missing_lines = "\n".join(f"• {m}" for m in _validation["missing"])
            logger.warning("⚠️ [ENGINE] VALIDATION FAILED — missing: %s", _validation["missing"])
            logger.warning("⚠️ [ENGINE] Corrigiendo automáticamente...")

            fix_request = (
                f"{params.get('request', user_message)}\n\n"
                f"{_validation['suggested_fix']}"
            )
            fix_extra = {**(extra_params or {}), "mode": "build"}
            fix_str = await _execute_action(
                intent=intent,
                decision_trace=decision_trace,
                user_message=fix_request,
                chat_id=chat_id,
                extra_params=fix_extra,
                _is_retry=True,
            )
            if fix_str:
                return (
                    f"⚠️ Faltan cosas:\n{missing_lines}\n\n"
                    f"Corrigiendo automáticamente...\n\n"
                    + fix_str
                )
            # Fix returned nothing — fall through with warning prefix
            _validation_prefix = f"⚠️ Faltan cosas:\n{missing_lines}\n\n"
        else:
            logger.warning("✅ [ENGINE] VALIDATION PASSED — proyecto completo")

    # 4. Log
    ActionLogger.log(
        user_id=user_id,
        action_type=action.action_type,
        params=params,
        result=result,
        approved=approved,
        duration_ms=duration_ms,
    )

    # 5. Format response for user
    if result.get("success"):
        logger.info(f"✅ Action executed successfully in {duration_ms}ms")
        formatted = _format_action_result(action, result)
        if _validation_prefix:
            return _validation_prefix + formatted
        return formatted
    else:
        logger.error(f"❌ Action failed: {result.get('error')}")
        return _format_action_error(action, result)


def _extract_action_params(intent: str, user_message: str) -> Dict[str, Any]:
    """
    Extrae parámetros de acción del mensaje del usuario.

    Para notion_create, extrae título y contenido después de "llamada" o "titulada".

    Args:
        intent: Intención detectada
        user_message: Mensaje original del usuario

    Returns:
        Dict con parámetros extraídos
    """
    params: Dict[str, Any] = {}

    if intent == "file_write":
        import re
        msg = user_message
        # Extract filename: "llamado test.txt", "named test.txt", or bare filename.ext
        name_match = re.search(
            r'(?:llamad[oa]|named?)\s+["\'“”]?([^\s"\'""]+)["\'“”]?',
            msg, re.IGNORECASE
        )
        if name_match:
            params["name"] = name_match.group(1).strip().rstrip(",")
        else:
            ext_match = re.search(r'\b(\w[\w\-]*\.\w+)\b', msg)
            if ext_match:
                params["name"] = ext_match.group(1)

        # Extract content: 'hola mundo' or "hola mundo" after contenido/que diga
        content_match = re.search(
            r'(?:contenido|que diga)[:\s]+["\'“”]([^"\'""]+)["\'“”]',
            msg, re.IGNORECASE
        )
        if content_match:
            params["content"] = content_match.group(1).strip()
        else:
            # Fallback: grab any quoted string
            fallback = re.search(r'["\'“”]([^"\'""]+)["\'“”]', msg)
            if fallback and "name" in params and fallback.group(1) != params.get("name"):
                params["content"] = fallback.group(1).strip()

    elif intent == "notion_create":
        # Intentar extraer título después de "llamada" o "titulada"
        msg = user_message
        import re
        title_match = re.search(
            r'(?:llamada|llamado|titulada|titulado|con el nombre)\s+"([^"]+)"',
            msg,
            re.IGNORECASE
        )
        if not title_match:
            title_match = re.search(
                r'(?:llamada|llamado|titulada|titulado)\s+([a-zA-Záéíóúñ ]+)',
                msg,
                re.IGNORECASE
            )
        if title_match:
            params["title"] = title_match.group(1).strip()
        else:
            # Fallback: usar las primeras palabras después del intent
            params["title"] = user_message[:50]

        # Intentar extraer contenido después de "contenido:" o "que diga:"
        content_match = re.search(
            r'(?:contenido|que diga|que diga:)\s+"([^"]+)"',
            msg,
            re.IGNORECASE
        )
        if content_match:
            params["content"] = content_match.group(1).strip()

    return params


def _detect_code_language(code: str) -> str:
    """
    Content-based heuristic language tag. Used when a file path is unavailable.
    """
    c = code.strip()
    cl = c.lower()
    if "import react" in cl or "react native" in cl or "<view" in cl or "<text" in cl:
        return "jsx"
    if "from fastapi" in cl or "from flask" in cl or "from django" in cl:
        return "python"
    # "def " is unambiguous Python in all common languages
    if "def " in c:
        return "python"
    if "class " in c and ("import " in cl or "from " in cl):
        return "python"
    if "async fn " in c or "impl " in c or "fn main" in c:
        return "rust"
    if "func " in c and ("package " in cl or "import (" in c):
        return "go"
    if "interface " in c and ": " in c and ("export " in c or "const " in c):
        return "typescript"
    return "javascript"


_EXT_LANG: Dict[str, str] = {
    "tsx": "tsx", "ts": "typescript",
    "jsx": "jsx", "js": "javascript",
    "py": "python", "rs": "rust", "go": "go",
    "kt": "kotlin", "swift": "swift", "java": "java",
    "css": "css", "scss": "scss", "json": "json",
    "yaml": "yaml", "yml": "yaml", "sh": "bash",
}


def _lang_from_path(path: str) -> str:
    """Extension-based language tag — more accurate than content heuristics."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _EXT_LANG.get(ext, "javascript")


def _render_file_list(label: str, icon: str, files: list) -> list:
    """Render a labeled file list section for a blueprint."""
    lines = [f"\n{icon} **{label}:**"]
    for f in files:
        path = f.get("path", "")
        desc = f.get("description", "")
        entry = f"  • `{path}`"
        if desc:
            entry += f" — {desc}"
        lines.append(entry)
    return lines


def _render_blueprint(project: Dict[str, Any]) -> str:
    """Render a blueprint project plan as a Telegram-friendly message.

    Handles both the V2 format (frontend/backend split) and the legacy
    flat format (files list) so fallback blueprints still render correctly.
    """
    name = project.get("name", "proyecto")
    description = project.get("description", "")
    frontend = project.get("frontend", [])
    backend = project.get("backend", [])
    files = project.get("files", [])       # legacy flat format
    deps = project.get("dependencies", [])
    steps = project.get("steps", [])

    lines = [f"📦 **Proyecto propuesto:** `{name}`"]
    if description:
        lines.append(f"\n{description}")

    if frontend or backend:
        # V2 multi-agent format
        if frontend:
            lines.extend(_render_file_list("Frontend", "👷", frontend))
        if backend:
            lines.extend(_render_file_list("Backend", "🏗️", backend))
    elif files:
        # Legacy flat format
        lines.extend(_render_file_list("Archivos", "📁", files))

    if deps:
        lines.append("\n📦 **Dependencias:**")
        for dep in deps:
            lines.append(f"  • `{dep}`")

    if steps:
        lines.append("\n⚙️ **Pasos:**")
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")

    lines.append("\n👉 Responde **aprobado** para construir este proyecto")
    return "\n".join(lines)


def _format_action_result(action: Any, result: Dict[str, Any]) -> str:
    """
    Formatea el resultado exitoso de una acción para mostrar al usuario.
    """
    action_result = result.get("result", {})

    # ── CodeAction ────────────────────────────────────────────────────
    if action.action_type == "CodeAction":
        # ── Blueprint mode: plan without code ─────────────────────────
        if (
            isinstance(action_result, dict)
            and action_result.get("mode") == "blueprint"
        ):
            return _render_blueprint(action_result.get("project", {}))

        operation = result.get("metadata", {}).get("operation", "generate")
        header = {
            "generate": "✅ Código generado por **El Forjador**:",
            "refactor": "✅ Código refactorizado por **El Forjador**:",
            "debug":    "✅ Código corregido por **El Forjador**:",
        }.get(operation, "✅ **El Forjador**:")

        # ── Multi-file result (build mode) ────────────────────────────
        if isinstance(action_result, dict) and "files" in action_result:
            files = action_result["files"]
            if not files:
                return "⚠️ El Forjador generó una respuesta vacía."

            blocks = [header]
            for f in files:
                path = f.get("path", "archivo")
                content = f.get("content", "").strip()
                lang = _lang_from_path(path)
                blocks.append(f"📁 `{path}`\n\n```{lang}\n{content}\n```")

            rendered = "\n\n---\n\n".join(blocks)

            project_path = result.get("_project_path")
            if project_path:
                files_written = result.get("_files_written", len(files))
                rendered += (
                    f"\n\n---\n\n"
                    f"📁 **Ruta:**\n"
                    f"`{project_path}`\n"
                    f"📄 {files_written} archivo(s) escritos"
                )

            run_result = result.get("_run_result")
            if run_result and run_result.get("success"):
                r = run_result["result"]
                _cmd = r.get("command", [])
                run_cmd = r.get("command_str") or (" ".join(_cmd) if isinstance(_cmd, list) else str(_cmd))
                if r.get("mode") == "streaming":
                    pid = r.get("pid", "?")
                    project_id = r.get("project_id", "")
                    rendered += (
                        f"\n\n---\n\n"
                        f"🚀 **Ejecutando:** `{run_cmd}`\n"
                        f"🔢 PID: `{pid}`\n"
                        f"📊 Ver logs en vivo: dashboard → `{project_id}`"
                    )
                else:
                    output = (r.get("stdout") or r.get("stderr") or "(sin output)").strip()
                    rendered += (
                        f"\n\n---\n\n"
                        f"🚀 **Ejecución:** `{run_cmd}`\n\n"
                        f"📄 **Output:**\n```\n{output[:500]}\n```"
                    )
                    if r.get("timed_out"):
                        rendered += "\n\n⏱️ _(proceso detenido tras 15s — servidor iniciado)_"

            return rendered

        # ── Single-file result (refactor / debug / fallback) ──────────
        code = action_result if isinstance(action_result, str) else str(action_result or "")
        if not code.strip():
            return "⚠️ El Forjador generó una respuesta vacía."
        lang = _detect_code_language(code)
        return f"{header}\n\n```{lang}\n{code}\n```"

    # ── FileAction ────────────────────────────────────────────────────
    if action.action_type == "FileAction":
        inner = action_result if isinstance(action_result, dict) else {}
        name = inner.get("name", "?")
        path = inner.get("path", "?")
        return f"✅ Archivo creado: `{name}`\n📁 Ruta: `{path}`"

    # ── NotionAction ──────────────────────────────────────────────────
    if action.action_type == "NotionAction":
        page_title = action_result.get("title", "Sin título") if isinstance(action_result, dict) else "Sin título"
        page_url = action_result.get("url", "") if isinstance(action_result, dict) else ""
        lines = [f"✅ Página creada en Notion: **{page_title}**"]
        if page_url:
            lines.append(f"🔗 {page_url}")
        return "\n".join(lines)

    # ── Formato genérico para otras acciones ──────────────────────────
    return f"✅ Acción ejecutada: {action.get_description()}"


def _format_action_error(action: Any, result: Dict[str, Any]) -> str:
    """
    Formatea el error de una acción para mostrar al usuario.
    """
    error = result.get("error", "Error desconocido")
    return f"❌ Error al ejecutar {action.get_description()}: {error}"


# ═══════════════════════════════════════════════════════════════════
# MULTI-AGENT BUILD HELPERS
# ═══════════════════════════════════════════════════════════════════

def _format_multi_agent_result(
    project_name: str,
    frontend_files: list,
    backend_files: list,
    project_path: Optional[str],
    files_written: int,
    run_command: Optional[list] = None,
    run_output: Optional[str] = None,
) -> str:
    """Format the multi-agent build result for the user."""
    lines = ["✅ **Proyecto construido y ejecutado**\n" if run_command else "✅ **Proyecto construido por múltiples agentes**\n"]

    if frontend_files:
        lines.append("👷 **Frontend (El Forjador):**")
        for f in frontend_files:
            lines.append(f"  • `{f['path']}`")

    if backend_files:
        lines.append("\n🏗️ **Backend (Arquitecto):**")
        for f in backend_files:
            lines.append(f"  • `{f['path']}`")

    if project_path:
        lines.append(f"\n📁 **Ruta:**\n`{project_path}`")
        lines.append(f"📄 {files_written} archivo(s) escritos")

    if run_command:
        cmd_display = " ".join(run_command) if isinstance(run_command, list) else str(run_command)
        if run_output and run_output.startswith("[streaming]"):
            lines.append(f"\n🚀 **Ejecutando:** `{cmd_display}`")
            lines.append(f"📊 {run_output}")
        else:
            lines.append(f"\n🚀 **Ejecución:** `{cmd_display}`")
            if run_output:
                lines.append(f"\n📄 **Output:**\n```\n{run_output[:500]}\n```")

    return "\n".join(lines)


async def _execute_multi_agent_build(
    blueprint: Dict[str, Any],
    original_request: str,
    chat_id: int,
) -> Optional[str]:
    """
    Run frontend and backend agents independently, merge their files,
    persist the project to disk, and return a formatted result message.
    """
    user_id = str(chat_id)
    project_name = blueprint.get("name", "proyecto")
    description = blueprint.get("description", "")

    fe_paths = ", ".join(f["path"] for f in blueprint.get("frontend", []))
    be_paths = ", ".join(f["path"] for f in blueprint.get("backend", []))
    base = f"{original_request}\nProyecto: {project_name} — {description}"

    frontend_request = f"{base}\nConstruye SOLO el frontend. Archivos esperados: {fe_paths}"
    backend_request = f"{base}\nConstruye SOLO el backend API. Archivos esperados: {be_paths}"

    # Build agent instances via registry
    FrontendCls = _agent_registry.get("frontend")  # CodeAction
    BackendCls = _agent_registry.get("backend")    # BackendAction

    frontend_agent = FrontendCls({
        "operation": "generate",
        "params": {"request": frontend_request, "mode": "build"},
        "decision_trace": {},
        "user_id": user_id,
    }) if FrontendCls else None

    backend_agent = BackendCls({
        "params": {"request": backend_request},
        "user_id": user_id,
    }) if BackendCls else None

    # Execute agents concurrently
    # Track slot order so results[i] maps back to the correct agent.
    _tasks = []
    _slots: list = []  # "frontend" | "backend" — parallel to _tasks

    if frontend_agent:
        _tasks.append(frontend_agent.execute())
        _slots.append("frontend")

    if backend_agent:
        _tasks.append(backend_agent.execute())
        _slots.append("backend")

    raw_results = await asyncio.gather(*_tasks, return_exceptions=True)

    all_files: list = []
    frontend_files_result: list = []
    backend_files_result: list = []

    for slot, result in zip(_slots, raw_results):
        if isinstance(result, Exception):
            logger.error("❌ %s agent raised exception: %s", slot.capitalize(), result, exc_info=result)
            continue

        if not (result.get("success") and isinstance(result.get("result"), dict)):
            logger.warning("⚠️ %s agent returned failure: %s", slot.capitalize(), result.get("error"))
            continue

        files = result["result"].get("files", [])
        all_files.extend(files)

        if slot == "frontend":
            frontend_files_result = files
            logger.info("👷 Frontend agent: %d file(s) generated", len(files))
        else:
            backend_files_result = files
            logger.info("🏗️ Backend agent: %d file(s) generated", len(files))

    if not all_files:
        return "⚠️ Ningún agente generó archivos. Intenta de nuevo."

    # ValidationLayer — check completeness before persisting
    _multi_validation_prefix: Optional[str] = None
    _vl = ValidationLayer()
    _validation = _vl.validate(original_request, {"files": all_files})
    if not _validation["is_valid"]:
        missing_lines = "\n".join(f"• {m}" for m in _validation["missing"])
        logger.warning("⚠️ [ENGINE] VALIDATION FAILED (multi-agent) — missing: %s", _validation["missing"])
        logger.warning("⚠️ [ENGINE] Corrigiendo automáticamente...")
        fix_request = (
            f"{original_request}\n\n{_validation['suggested_fix']}"
        )
        fix_str = await _execute_action(
            intent="code_generate",
            decision_trace={
                "intent": "code_generate",
                "changed": False,
                "source": "validation_fix",
                "confidence": 1.0,
            },
            user_message=fix_request,
            chat_id=chat_id,
            extra_params={"mode": "build"},
            _is_retry=True,
        )
        if fix_str:
            return (
                f"⚠️ Faltan cosas:\n{missing_lines}\n\n"
                f"Corrigiendo automáticamente...\n\n"
                + fix_str
            )
        _multi_validation_prefix = f"⚠️ Faltan cosas:\n{missing_lines}\n\n"
    else:
        logger.warning("✅ [ENGINE] VALIDATION PASSED (multi-agent) — proyecto completo")

    # Persist to disk via FileAction
    project_path: Optional[str] = None
    files_written = 0
    run_cmd_used: Optional[list] = None
    run_output: Optional[str] = None
    try:
        file_action = FileAction({
            "operation": "write_project",
            "params": {"files": all_files},
        })
        write_result = await file_action.execute()
        inner = write_result.get("result") or {}
        if write_result.get("success") and inner.get("project_path"):
            project_path = inner["project_path"]
            files_written = inner.get("files_written", len(all_files))
            logger.info(
                "💾 Multi-agent project saved → %s (%d file(s))",
                project_path, files_written,
            )
            # Git checkpoint after multi-agent write (best-effort)
            try:
                from core.git_manager import checkpoint as _git_checkpoint
                _git_checkpoint(Path(project_path), "[AI] generated app")
            except Exception as _ge:
                logger.warning("⚠️ Git checkpoint (multi-agent) failed: %s", _ge)

            # Auto-run: allocate a free port and detect the start command
            _multi_port = find_free_port()
            run_cmd_used = get_run_command(project_path, all_files, port=_multi_port)
            if run_cmd_used:
                # Mark as known BEFORE awaiting CommandAction so RuntimeEngine's
                # scan (which runs during the asyncio yield inside create_subprocess_exec)
                # sees this project in _known and skips a duplicate launch.
                _pid = Path(project_path).name
                try:
                    from core.runtime.runtime_engine import get_engine as _get_re
                    _get_re()._known.add(_pid)
                except Exception:
                    pass

                _cmd_action = CommandAction({
                    "operation": "run",
                    "params": {
                        "command": run_cmd_used,
                        "cwd": project_path,
                        "project_id": _pid,
                    },
                })
                try:
                    _run_result = await _cmd_action.execute()
                    if _run_result.get("success"):
                        r = _run_result.get("result", {})
                        if r.get("mode") == "streaming":
                            run_output = f"[streaming] pid={r.get('pid', '?')} — ver dashboard"
                        else:
                            run_output = r.get("stdout") or r.get("stderr") or "(sin output)"
                        logger.info(
                            "🚀 Multi-agent auto-run: '%s' mode=%s",
                            run_cmd_used, r.get("mode", "legacy"),
                        )
                        # Schedule repair watcher — detects post-launch crashes
                        try:
                            asyncio.create_task(
                                _get_re()._repair_loop(_pid, Path(project_path))
                            )
                            logger.info("🔧 [FORJADOR] repair watcher scheduled for '%s'", _pid)
                        except Exception as _rew_exc:
                            logger.warning("⚠️ Could not schedule repair watcher: %s", _rew_exc)
                except Exception as _exc:
                    logger.warning("⚠️ Multi-agent auto-run failed: %s", _exc)
    except Exception as exc:
        logger.warning("⚠️ Could not save multi-agent project: %s", exc)

    formatted_result = _format_multi_agent_result(
        project_name=project_name,
        frontend_files=frontend_files_result,
        backend_files=backend_files_result,
        project_path=project_path,
        files_written=files_written,
        run_command=run_cmd_used,
        run_output=run_output,
    )
    if _multi_validation_prefix:
        return _multi_validation_prefix + formatted_result
    return formatted_result


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

    # ── Intent detection — EARLY, before prefix checks ─────────────────
    # Must be computed here so prefix guards can use it. Re-used below.
    intent = MemoryDecisionLayer._detect_intent(user_message.lower().strip())

    # ── Detectar comandos directos ──────────────────────────
    if user_lower.startswith("ejecutar "):
        plan_id = user_message[len("ejecutar "):].strip()
        if plan_id:
            logger.info(f"⚡ Comando directo: ejecutar plan '{plan_id}'")
            result = await call_execute_plan(plan_id)
            if "error" in result:
                return f"⚠️ Error al ejecutar plan:\n{result['error']}"
            return _format_execution_result(result)

    # Guard: don't treat file/command requests as build_app calls
    if user_lower.startswith(("plan ", "build ", "crea ", "construye ")) and not intent.startswith(("file_", "command_")):
        for prefix in ("plan ", "build ", "crea ", "construye "):
            if user_lower.startswith(prefix):
                idea = user_message[len(prefix):].strip()
                break
        if idea:
            logger.info(f"🔨 Comando directo: build_app con idea '{idea}'")
            result = await call_build_app(idea)
            if "error" in result:
                return f"⚠️ Error al generar plan:\n{result['error']}"
            if not result.get("plan_id"):
                return result.get("message", "⚠️ Backend respondió sin plan_id")
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

    # ── El Forjador: approval override ──────────────────────────────
    # Exact-match only: the entire message must be a confirmation token.
    # This prevents questions and new code requests from triggering a build.
    if (
        state.get("forjador_state") == "WAITING_BUILD_APPROVAL"
        and _is_explicit_approval(user_message)
        and not (intent and intent.startswith("code_"))
    ):
        intent = "code_generate"
        logger.info("🏗️ El Forjador: explicit approval → intent overridden to code_generate")

    # ── Bug #5 fix: active app request routing ──────────────────────
    # If an app is running and the user wants to test/request an endpoint,
    # route to curl instead of generating new code.
    _REQUEST_PATTERNS = [
        "haz request", "make request", "prueba el endpoint",
        "test endpoint", "prueba endpoint", "request a /", "get /",
    ]
    _msg_low = user_message.lower()
    if (
        _active_app
        and intent in ("code_generate", None)
        and any(p in _msg_low for p in _REQUEST_PATTERNS)
    ):
        # Extract endpoint if user mentioned one (e.g. "haz request a /ping")
        _ep = "/ping"
        for _part in user_message.split():
            if _part.startswith("/"):
                _ep = _part.rstrip(".,;")
                break
        intent = "command_run"
        if "params" not in context:
            context["params"] = {}
        context["params"]["command"] = [
            "curl", f"http://localhost:{_active_app['port']}{_ep}"
        ]
        logger.info(
            "📡 Active-app routing: curl %s on port %s",
            _ep, _active_app["port"],
        )

    # ═══════════════════════════════════════════════════════════════
    # PRE-AI ACTION GATE
    # ALL actions are decided and executed HERE, before the AI loop.
    # The AI loop is only reached when no action matches.
    # ═══════════════════════════════════════════════════════════════

    if intent and intent.startswith("code_"):
        # ── Determine execution mode ────────────────────────────────
        build_approved = (
            state.get("forjador_state") == "WAITING_BUILD_APPROVAL"
            and _is_explicit_approval(user_message)
        )
        mode = "build" if build_approved else "blueprint"

        # In build mode, recall the original request stored at blueprint time
        actual_request = (
            state.get("forjador_pending_request", user_message)
            if build_approved else user_message
        )

        logger.info(
            "🔥 El Forjador: mode='%s' intent='%s' request='%s...'",
            mode, intent, actual_request[:60],
        )

        decision_trace = {
            "intent": intent,
            "changed": False,
            "source": "el_forjador_force",
            "confidence": 1.0,
        }
        decision_trace_container.append(decision_trace)

        # ── Blueprint phase: PlannerAgent generates the plan ────────
        if mode == "blueprint":
            planner = PlannerAgent(request=actual_request)
            plan_result = await planner.execute()

            if plan_result.get("success"):
                state["forjador_pending_request"] = user_message
                state["approved_blueprint"] = plan_result["result"]["project"]
                if _wants_auto_approve(user_message):
                    # auto_aprobar=true → execute build phase immediately, no human wait.
                    # IMPORTANT: do NOT "fall through" — the build else-branch is unreachable
                    # from here; we must run the build logic inline and return.
                    logger.info("🏗️ [FORJADOR] auto_aprobar=true → building immediately")
                    state["forjador_state"] = "WAITING_BUILD_APPROVAL"
                    save_states()
                    _bp = state.get("approved_blueprint")
                    if _bp and _bp.get("frontend") and _bp.get("backend"):
                        _auto_result = await _execute_multi_agent_build(
                            blueprint=_bp,
                            original_request=actual_request,
                            chat_id=chat_id,
                        )
                    else:
                        _auto_result = await _execute_action(
                            intent="code_generate",
                            decision_trace=decision_trace,
                            user_message=actual_request,
                            chat_id=chat_id,
                            extra_params={"mode": "build"},
                        )
                    state.pop("forjador_pending_request", None)
                    state.pop("forjador_state", None)
                    state.pop("approved_blueprint", None)
                    save_states()
                    logger.info("✅ [FORJADOR] request handled completely — stopping AI loop")
                    return _auto_result or "⚠️ El Forjador no pudo construir el proyecto. Intenta de nuevo."
                else:
                    state["forjador_state"] = "WAITING_BUILD_APPROVAL"
                    save_states()
                    logger.info("📐 El Forjador: PlannerAgent blueprint ready, waiting for build approval")
                    return _render_blueprint(plan_result["result"]["project"])

            # PlannerAgent failed — fall back to CodeAction blueprint path
            logger.warning(
                "⚠️ PlannerAgent failed: %s — falling back to CodeAction blueprint",
                plan_result.get("error"),
            )
            action_result = await _execute_action(
                intent=intent,
                decision_trace=decision_trace,
                user_message=actual_request,
                chat_id=chat_id,
                extra_params={"mode": "blueprint"},
            )
            if action_result:
                state["forjador_pending_request"] = user_message
                state["forjador_state"] = "WAITING_BUILD_APPROVAL"
                save_states()
                if _wants_auto_approve(user_message):
                    # auto_aprobar=true on fallback path — build inline and return.
                    logger.info("🏗️ [FORJADOR] auto_aprobar=true → building immediately (fallback path)")
                    _bp = state.get("approved_blueprint")
                    if _bp and _bp.get("frontend") and _bp.get("backend"):
                        _auto_result = await _execute_multi_agent_build(
                            blueprint=_bp,
                            original_request=actual_request,
                            chat_id=chat_id,
                        )
                    else:
                        _auto_result = await _execute_action(
                            intent="code_generate",
                            decision_trace=decision_trace,
                            user_message=actual_request,
                            chat_id=chat_id,
                            extra_params={"mode": "build"},
                        )
                    state.pop("forjador_pending_request", None)
                    state.pop("forjador_state", None)
                    state.pop("approved_blueprint", None)
                    save_states()
                    logger.info("✅ [FORJADOR] request handled completely — stopping AI loop")
                    return _auto_result or "⚠️ El Forjador no pudo construir el proyecto. Intenta de nuevo."
                else:
                    logger.info("📐 El Forjador: blueprint stored (fallback), waiting for build approval")
                    return action_result

        # ── Build phase ─────────────────────────────────────────────
        else:
            blueprint = state.get("approved_blueprint")
            has_frontend = bool(blueprint and blueprint.get("frontend"))
            has_backend = bool(blueprint and blueprint.get("backend"))

            if has_frontend and has_backend:
                # Multi-agent build: run frontend + backend agents independently
                logger.info("🤝 El Forjador: multi-agent build — frontend + backend")
                action_result = await _execute_multi_agent_build(
                    blueprint=blueprint,
                    original_request=actual_request,
                    chat_id=chat_id,
                )
            else:
                # Single-agent fallback (no blueprint, or only one layer)
                logger.info("🏗️ El Forjador: single-agent build")
                action_result = await _execute_action(
                    intent=intent,
                    decision_trace=decision_trace,
                    user_message=actual_request,
                    chat_id=chat_id,
                    extra_params={"mode": "build"},
                )

            if action_result:
                state.pop("forjador_pending_request", None)
                state.pop("forjador_state", None)
                state.pop("approved_blueprint", None)
                save_states()
                logger.info("🏗️ El Forjador: build complete, state cleared")
                return action_result

        # El Forjador ran but produced no result (build failed, CodeAction returned None, etc.).
        # NEVER fall through to the AI loop — the LLM would improvise with notion_create
        # or other tools and produce garbage. Return a clean error instead.
        logger.warning(
            "⚠️ [FORJADOR] No result for intent='%s' — stopping AI loop to prevent improvisation",
            intent,
        )
        return (
            "⚠️ El Forjador no pudo procesar la solicitud. "
            "Por favor intenta de nuevo con más detalle."
        )

    elif _should_execute_action(intent):
        logger.info(f"⚡ Executing action BEFORE AI: {intent}")
        decision_trace = {
            "intent": intent,
            "changed": False,
            "source": "pre_ai_action",
            "confidence": 1.0,
        }
        decision_trace_container.append(decision_trace)

        pre_action_result = await _execute_action(
            intent=intent,
            decision_trace=decision_trace,
            user_message=user_message,
            chat_id=chat_id,
        )
        if pre_action_result:
            return pre_action_result

    max_iterations = 5
    for iteration in range(max_iterations):
        logger.info(f"🔄 Iteración {iteration + 1}")

        try:
            # Elegir tools según intent: archivos → FILESYSTEM_TOOLS, resto → NOTION_TOOLS
            _ai_tools = FILESYSTEM_TOOLS if intent and intent.startswith("file_") else NOTION_TOOLS
            response, api_used = await call_ai_with_fallback(messages, tools=_ai_tools)
            content = response["content"]
            raw = response["raw"]
            assistant_message = raw.choices[0].message

            logger.info(f"🤖 AI RESPONSE: {content[:200]}")
            logger.info(f"🧠 Provider: {response.get('provider')}")

            # ═══════════════════════════════════════════════════════════
            # NO TOOL CALLS — AI response only (conversational)
            # ═══════════════════════════════════════════════════════════
            if not hasattr(assistant_message, 'tool_calls') or not assistant_message.tool_calls:

                # ── 1. Pattern extraction ──
                try:
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

                # ── 2. BehaviorPipeline ──
                try:
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
                    decision_trace_container.append(decision_trace)

                except Exception as e:
                    logger.warning("⚠️ BehaviorPipeline fallback failed: %s", e)

                # ── 3. Return AI content ──
                return content or "Sin respuesta"

            # ═══════════════════════════════════════════════════════════
            # TOOL CALLS — AI quiere ejecutar herramientas
            # ═══════════════════════════════════════════════════════════
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

                # ── file_create — acción filesystem via ActionSystem ──────
                if function_name == "file_create":
                    logger.info("⚡ Tool call 'file_create' routed through ActionSystem")
                    _fc_trace = {
                        "intent": "file_write",
                        "changed": False,
                        "source": "tool_call",
                        "confidence": 1.0,
                    }
                    decision_trace_container.append(_fc_trace)
                    _fc_context = {
                        "user_id": str(chat_id),
                        "params": {
                            "name": function_args.get("name", "output.txt"),
                            "content": function_args.get("content", ""),
                            "request": user_message,
                        },
                        "decision_trace": _fc_trace,
                        "user_message": user_message,
                    }
                    _fc_action = ActionRouter.route(_fc_trace, "file_write", _fc_context)
                    if _fc_action is not None:
                        _fc_start = time.time()
                        try:
                            _fc_result = await _fc_action.execute()
                            result = _fc_result.get("result", _fc_result)
                        except Exception as _e:
                            result = {"error": str(_e)}
                        ActionLogger.log(
                            user_id=str(chat_id),
                            action_type=_fc_action.action_type,
                            params=function_args,
                            result=result if isinstance(result, dict) else {"result": result},
                            approved=None,
                            duration_ms=int((time.time() - _fc_start) * 1000),
                        )
                    else:
                        result = {"error": "Failed to route file_create through ActionSystem"}

                # ── Tool de LECTURA (información, no acciones) ──
                elif function_name == "notion_search":
                    result = await notion_search(function_args["query"])

                elif function_name == "notion_fetch":
                    result = await notion_fetch(function_args["page_id"])

                # ════════════════════════════════════════════════════════
                # ⚡ ACCIÓN — SIEMPRE via ActionRouter (NUNCA directo)
                # ════════════════════════════════════════════════════════
                elif function_name == "notion_create":
                    logger.info("⚡ Tool call 'notion_create' routed through ActionSystem")
                    intent_from_tool = "notion_create"
                    decision_trace = {
                        "intent": intent_from_tool,
                        "changed": False,
                        "source": "tool_call",
                        "confidence": 1.0,
                    }
                    decision_trace_container.append(decision_trace)

                    # Construir contexto con parámetros del AI (no del mensaje usuario)
                    action_context = {
                        "user_id": str(chat_id),
                        "params": {
                            "title": function_args.get("title", ""),
                            "content": function_args.get("content", ""),
                            "parent_id": function_args.get("parent_id", ""),
                        },
                        "decision_trace": decision_trace,
                    }

                    action = ActionRouter.route(decision_trace, intent_from_tool, action_context)
                    if action is not None:
                        logger.info(f"⚡ Action routed: {action.action_type} (via tool_call)")
                        action_start = time.time()
                        try:
                            action_exec_result = await action.execute()
                            result = action_exec_result.get("result", action_exec_result)
                        except Exception as e:
                            logger.error(f"❌ Action execution failed: {e}")
                            result = {"error": str(e)}
                        duration_ms = int((time.time() - action_start) * 1000)
                        ActionLogger.log(
                            user_id=str(chat_id),
                            action_type=action.action_type,
                            params=function_args,
                            result=result if isinstance(result, dict) else {"result": result},
                            approved=None,  # Tool calls bypass approval
                            duration_ms=duration_ms,
                        )
                    else:
                        logger.error("❌ ActionRouter returned None for notion_create tool call")
                        result = {"error": "Failed to route notion_create through ActionSystem"}

                elif function_name == "build_app":
                    # Blocked: code intents are fully handled by El Forjador pre-AI.
                    # If the AI reaches this point it means El Forjador did not short-circuit
                    # properly. Return immediately — do NOT let the AI loop continue and
                    # improvise with other tools (notion_create, etc.).
                    logger.warning(
                        "🚫 [FORJADOR] build_app tool_call blocked — stopping AI loop immediately"
                    )
                    return (
                        "⚠️ El Forjador detectó un intento de generación de código dentro "
                        "del loop conversacional. Esto es un bug de orquestación. "
                        "Por favor repite tu solicitud."
                    )

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


# ═══════════════════════════════════════════════════════════════════
# EXECUTION ENGINE — public entry point
# ═══════════════════════════════════════════════════════════════════

class ExecutionEngine:
    """
    Motor de ejecución central: intent detection → action routing →
    action execution → result handling → learning loop.
    """

    async def run(
        self,
        user_message: str,
        user_id: str,
        state: dict,
    ) -> str:
        # Convert user_id back to int for Telegram-aware subsystems
        chat_id: int = int(user_id)

        # ═══════════════════════════════════════════════════════════
        # STEP 1 — LOAD persisted learning loop state
        # ═══════════════════════════════════════════════════════════
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

        _decision_trace_container: List[Dict[str, Any]] = []

        # ═══════════════════════════════════════════════════════════
        # STEP 2 — Process the message
        # ═══════════════════════════════════════════════════════════
        result = await _process_message_inner(
            user_message, chat_id, state,
            persisted_identity, performance_state, config,
            _decision_trace_container,
        )

        # ═══════════════════════════════════════════════════════════
        # STEP 3 — FEEDBACK LOOP (if a behavior decision was made)
        # ═══════════════════════════════════════════════════════════
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

        # ═══════════════════════════════════════════════════════════
        # STEP 4 — SAVE persisted learning loop state
        # ═══════════════════════════════════════════════════════════
        _persist_learning_state(user_id, persisted_identity, performance_state, config)

        return result
