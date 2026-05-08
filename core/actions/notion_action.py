# core/actions/notion_action.py

from core.actions.base_action import BaseAction
from core.notion_gateway import notion_create_child_page, notion_search, notion_fetch
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

# ID por defecto de la página raíz de NexusAgentes en Notion
DEFAULT_PARENT_ID = "34c5a25084b081b4af59c4f86c95785a"


class NotionAction(BaseAction):
    """
    Executor de acciones en Notion.

    Operaciones soportadas:
    - create: Crear página (vía notion_create_child_page)
    - update: Actualizar página (TODO)
    - move: Mover página (TODO)
    - delete: Eliminar página (TODO)
    """

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        self.operation = context.get("operation")  # create, update, move, delete
        self.params = context.get("params", {})

    async def execute(self) -> Dict[str, Any]:
        """
        Ejecuta la operación de Notion (async).

        Returns:
            Dict con formato:
            {
                "success": bool,
                "result": Any,
                "error": Optional[str]
            }
        """
        try:
            if self.operation == "create":
                return await self._create_page()
            else:
                return {
                    "success": False,
                    "result": None,
                    "error": f"Operation '{self.operation}' not implemented yet",
                }
        except Exception as e:
            logger.error(f"❌ NotionAction failed: {e}")
            return {
                "success": False,
                "result": None,
                "error": str(e),
            }

    async def _create_page(self) -> Dict[str, Any]:
        """
        Crea una página en Notion usando notion_create_child_page.

        Params esperados:
        - parent_id: ID de la página padre (opcional, usa DEFAULT_PARENT_ID)
        - title: Título de la nueva página
        - content: Contenido markdown (opcional)
        """
        parent_id = self.params.get("parent_id") or DEFAULT_PARENT_ID
        title = self.params.get("title")
        content = self.params.get("content", "")

        if not title:
            return {
                "success": False,
                "result": None,
                "error": "Missing required param: title",
            }

        logger.info(f"📝 Creating Notion page: '{title}' under {parent_id}")

        result = await notion_create_child_page(
            parent_id=parent_id,
            title=title,
            content=content,
        )

        if "error" in result:
            logger.error(f"❌ Notion create failed: {result['error']}")
            return {
                "success": False,
                "result": None,
                "error": result["error"],
            }

        # Extraer información de la respuesta de la API
        page_id = result.get("id", "unknown")
        page_url = result.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        logger.info(f"✅ Notion page created: {title} (ID: {page_id})")
        return {
            "success": True,
            "result": {
                "page_id": page_id,
                "title": title,
                "url": page_url,
            },
            "error": None,
        }

    def requires_approval(self) -> bool:
        """Delete requiere aprobación, create/update/move no."""
        return self.operation == "delete"

    def get_description(self) -> str:
        """Descripción legible de la acción."""
        if self.operation == "create":
            return f"Crear página en Notion: '{self.params.get('title')}'"
        elif self.operation == "delete":
            return f"Eliminar página en Notion: '{self.params.get('page_id')}'"
        else:
            return f"Operación Notion: {self.operation}"
