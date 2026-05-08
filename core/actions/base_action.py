# core/actions/base_action.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseAction(ABC):
    """
    Clase base para todas las acciones ejecutables.

    Principios de diseño:
    - Determinista: sin AI, sin random
    - Fail-safe: retorna error gracefully, nunca crashea
    - Loggeable: toda acción debe ser registrable
    """

    def __init__(self, context: Dict[str, Any]):
        """
        Args:
            context: Diccionario con toda la info necesaria para ejecutar
                    Ejemplo: {"operation": "create", "params": {...}}
        """
        self.context = context
        self.action_type = self.__class__.__name__

    @abstractmethod
    async def execute(self) -> Dict[str, Any]:
        """
        Ejecuta la acción (async).

        Returns:
            Dict con formato:
            {
                "success": bool,
                "result": Any,
                "error": Optional[str]
            }
        """
        raise NotImplementedError

    def requires_approval(self) -> bool:
        """
        Determina si esta acción requiere aprobación del usuario.

        Returns:
            True si requiere aprobación, False si es autónoma
        """
        return False

    @abstractmethod
    def get_description(self) -> str:
        """
        Descripción legible de lo que hará esta acción.

        Returns:
            String descriptivo para mostrar al usuario
        """
        raise NotImplementedError
