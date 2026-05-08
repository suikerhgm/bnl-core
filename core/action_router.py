# core/action_router.py

from typing import Dict, Any, Optional
from core.actions.base_action import BaseAction
from core.actions.notion_action import NotionAction
from core.actions.file_action import FileAction
from core.actions.code_action import CodeAction
from core.actions.command_action import CommandAction
import logging

logger = logging.getLogger(__name__)


# ── Command parser ─────────────────────────────────────────────────────────────
# Sorted longest-first so more specific prefixes match before shorter ones.
_CMD_PREFIXES = sorted([
    "ejecuta este comando:",
    "ejecuta el comando:",
    "ejecuta:",
    "ejecuta",
    "run this command:",
    "run:",
    "run",
    "corre el comando:",
    "corre",
    "lanza",
], key=len, reverse=True)


def _parse_command_from_message(msg: str) -> list:
    """Extract command tokens from a plain-text user message.

    Strips known trigger prefixes and splits the remainder into tokens.
    Returns [] if no recognisable prefix is found or the remainder is empty.
    """
    norm = msg.strip().lower()
    for prefix in _CMD_PREFIXES:
        if norm.startswith(prefix):
            remainder = msg[len(prefix):].strip().lstrip(":").strip()
            if remainder:
                return remainder.split()
            break
    return []


class ActionRouter:
    """
    Enrutador de acciones — decide QUÉ acción ejecutar según decision_trace + intent.

    Este es el cerebro del Action System.
    """

    # Mapeo de intents a tipos de acción
    INTENT_ACTION_MAP = {
        "notion_create": NotionAction,
        "notion_update": NotionAction,
        "notion_delete": NotionAction,
        "notion_move": NotionAction,
        "file_read": FileAction,
        "file_write": FileAction,
        "file_delete": FileAction,
        "file_move": FileAction,
        "file_copy": FileAction,
        "code_refactor": CodeAction,
        "code_debug": CodeAction,
        "code_lint": CodeAction,
        "code_format": CodeAction,
        "code_generate": CodeAction,
        "command_run": CommandAction,
        "command_sudo": CommandAction,
        "command_script": CommandAction,
    }

    @staticmethod
    def route(
        decision_trace: Dict[str, Any],
        intent: str,
        context: Dict[str, Any],
    ) -> Optional[BaseAction]:
        """
        Analiza decision_trace + intent y retorna el Action apropiado.

        Args:
            decision_trace: Traza de decisión del BehaviorPipeline
            intent: Intención detectada (construir, organizar, corregir, etc.)
            context: Contexto adicional del mensaje

        Returns:
            Instancia de BaseAction o None si no hay acción que ejecutar
        """
        # Si no hay intent definido, no hay acción que ejecutar
        if not intent:
            logger.debug("No intent provided, skipping action routing")
            return None

        # Buscar la clase de acción correspondiente al intent
        action_class = ActionRouter.INTENT_ACTION_MAP.get(intent)

        if action_class is None:
            logger.warning(f"⚠️ No action mapped for intent: {intent}")
            return None

        # Extraer operación del intent (ej: "notion_create" → "create")
        operation = intent.split("_", 1)[1] if "_" in intent else intent

        # Construir contexto de acción combinando decision_trace + context.
        # user_message se propaga explícitamente a params["request"] y a
        # decision_trace["user_message"] para que _extract_user_request()
        # lo encuentre sin importar qué ruta de búsqueda use la acción.
        incoming_params = context.get("params", {})
        user_message = context.get("user_message") or incoming_params.get("request")

        action_context = {
            "operation": operation,
            "params": {
                **incoming_params,
                "request": incoming_params.get("request") or user_message,
            },
            "decision_trace": {
                **decision_trace,
                "user_message": user_message,
            },
            "user_id": context.get("user_id", "default"),
        }

        # If routing to a command action but no command was explicitly provided,
        # try to extract one from the user's raw message (Bug #1 fix).
        if action_class is CommandAction and not incoming_params.get("command"):
            parsed = _parse_command_from_message(user_message or "")
            if parsed:
                action_context["params"]["command"] = parsed
                logger.info("🔍 [ROUTER] parsed command from message: %s", parsed)

        try:
            action_instance = action_class(action_context)
            logger.info(
                f"🔄 Routed intent '{intent}' → {action_instance.action_type}"
            )
            return action_instance
        except Exception as e:
            logger.error(f"❌ Failed to instantiate action for intent '{intent}': {e}")
            return None

    @staticmethod
    def get_available_intents() -> list:
        """
        Retorna la lista de intents disponibles para routing.

        Returns:
            Lista de strings con los intents registrados
        """
        return list(ActionRouter.INTENT_ACTION_MAP.keys())
