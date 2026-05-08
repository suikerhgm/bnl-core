# core/approval_system.py

from typing import Dict, Any, Optional
from core.actions.base_action import BaseAction
import logging
import asyncio
import uuid

logger = logging.getLogger(__name__)

# Lista de acciones que requieren aprobación SIEMPRE
CRITICAL_ACTIONS = {
    "delete": True,
    "deploy": True,
    "payment": True,
    "file_delete": True,
    "command_sudo": True,
    "database_production": True,
}

# Storage temporal para pending approvals
# Key: approval_id, Value: asyncio.Future que se resuelve con True/False/None
_pending_approvals: Dict[str, asyncio.Future] = {}

# Timeout por defecto: 5 minutos
APPROVAL_TIMEOUT_SECONDS = 300


class ApprovalSystem:
    """
    Sistema de aprobaciones para acciones críticas.

    Envía mensaje a Leo vía Telegram y espera respuesta.
    Timeout de 5 minutos — si no responde, se cancela la acción.
    """

    @staticmethod
    def requires_approval(action_type: str) -> bool:
        """
        Determina si un tipo de acción requiere aprobación.

        Args:
            action_type: Tipo de acción (ej: "delete", "create", etc.)

        Returns:
            True si requiere aprobación, False si es autónoma
        """
        return action_type.lower() in CRITICAL_ACTIONS

    @staticmethod
    async def request_approval(
        action: BaseAction, telegram_chat_id: int
    ) -> Optional[bool]:
        """
        Solicita aprobación al usuario vía Telegram.

        Args:
            action: Instancia de la acción a aprobar
            telegram_chat_id: Chat ID de Telegram del usuario

        Returns:
            True (aprobada), False (rechazada), None (timeout)
        """
        approval_id = str(uuid.uuid4())[:8]  # ID corto para tracking

        # Crear Future para esperar respuesta
        future = asyncio.Future()
        _pending_approvals[approval_id] = future

        # Construir mensaje de aprobación
        message = (
            f"\U0001f512 **APROBACION REQUERIDA**\n\n"
            f"**Accion:** {action.action_type}\n"
            f"**Descripcion:** {action.get_description()}\n\n"
            f"\u00bfAprobar esta accion?\n\n"
            f"Responde:\n"
            f"- `/aprobar {approval_id}` para ejecutar\n"
            f"- `/rechazar {approval_id}` para cancelar\n\n"
            f"\u23f1\ufe0f Timeout: 5 minutos"
        )

        # Enviar mensaje vía Telegram (late import para evitar circular imports)
        try:
            from app.services.telegram_service import send_telegram_message

            success = await send_telegram_message(telegram_chat_id, message)
            if not success:
                logger.error(f"\u274c Failed to send approval request to Telegram: {approval_id}")
                _pending_approvals.pop(approval_id, None)
                return None

            logger.info(f"\U0001f4e4 Approval request sent: {approval_id}")
        except Exception as e:
            logger.error(f"\u274c Failed to send approval request: {e}")
            _pending_approvals.pop(approval_id, None)
            return None

        # Esperar respuesta con timeout de 5 minutos
        try:
            result = await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT_SECONDS)
            logger.info(f"\u2705 Approval resolved: {approval_id} \u2192 {result}")
            return result
        except asyncio.TimeoutError:
            logger.warning(f"\u23f0 Approval timeout: {approval_id}")
            return None
        except Exception as e:
            logger.error(f"\u274c Approval error: {e}")
            return None
        finally:
            # Cleanup
            _pending_approvals.pop(approval_id, None)

    @staticmethod
    def resolve_approval(approval_id: str, approved: bool) -> bool:
        """
        Resuelve una aprobación pendiente.

        Args:
            approval_id: ID de la aprobación (del mensaje)
            approved: True (aprobar), False (rechazar)

        Returns:
            True si se resolvió correctamente, False si no existe
        """
        future = _pending_approvals.get(approval_id)
        if future is None:
            logger.warning(f"\u26a0\ufe0f Approval ID not found: {approval_id}")
            return False

        if future.done():
            logger.warning(f"\u26a0\ufe0f Approval already resolved: {approval_id}")
            return False

        future.set_result(approved)
        logger.info(f"\u2705 Approval resolved: {approval_id} \u2192 {approved}")
        return True

    @staticmethod
    def describe_required_approvals(action: BaseAction) -> str:
        """
        Describe qué aprobaciones se requieren para una acción.

        Args:
            action: Instancia de la acción a evaluar

        Returns:
            String descriptivo del estado de aprobación
        """
        if action.requires_approval():
            return (
                f"\U0001f512 La accion {action.action_type} requiere aprobacion. "
                f"Descripcion: {action.get_description()}"
            )
        return (
            f"\U0001f513 La accion {action.action_type} es autonoma. "
            f"No requiere aprobacion."
        )

    @staticmethod
    def get_pending_count() -> int:
        """
        Retorna la cantidad de aprobaciones pendientes.

        Returns:
            Número de aprobaciones esperando respuesta
        """
        return len(_pending_approvals)
