# core/action_logger.py

from core.persistence import save_action_log, get_action_history
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ActionLogger:
    """
    Registrador de acciones ejecutadas.

    Persiste en SQLite para análisis posterior y aprendizaje.
    """

    @staticmethod
    def log(
        user_id: str,
        action_type: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        approved: Optional[bool],
        duration_ms: int,
    ):
        """
        Registra una acción ejecutada.

        Args:
            user_id: ID del usuario que disparó la acción
            action_type: Tipo de acción (NotionAction, FileAction, etc.)
            params: Parámetros de la acción
            result: Resultado de la ejecución
            approved: True (aprobada), False (rechazada), None (autónoma)
            duration_ms: Tiempo de ejecución en milisegundos
        """
        try:
            save_action_log(user_id, action_type, params, result, approved, duration_ms)
            logger.info(f"✅ Action logged: {action_type} for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to log action: {e}")

    @staticmethod
    def get_history(user_id: str, limit: int = 10) -> list:
        """
        Recupera historial de acciones del usuario.

        Args:
            user_id: ID del usuario
            limit: Número máximo de registros a retornar

        Returns:
            Lista de diccionarios con historial de acciones
        """
        return get_action_history(user_id, limit)

    @staticmethod
    def get_summary(user_id: str, limit: int = 10) -> str:
        """
        Genera un resumen legible del historial de acciones.

        Args:
            user_id: ID del usuario
            limit: Número máximo de registros a incluir

        Returns:
            String con resumen formateado
        """
        history = get_action_history(user_id, limit)

        if not history:
            return f"No hay acciones registradas para el usuario '{user_id}'."

        lines = [f"📋 Historial de acciones para {user_id} (últimas {len(history)}):"]
        for entry in history:
            approved_str = {
                None: "⚙️ autónoma",
                1: "✅ aprobada",
                0: "❌ rechazada",
            }.get(entry.get("approved"))

            success_str = "✅" if entry.get("success") else "❌"
            lines.append(
                f"  [{entry.get('executed_at', '?')}] "
                f"{entry.get('action_type', '?')} "
                f"({approved_str}) {success_str} "
                f"{entry.get('duration_ms', '?')}ms"
            )

        return "\n".join(lines)
