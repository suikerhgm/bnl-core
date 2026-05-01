"""
Definiciones de herramientas para function calling de la IA.
"""
from typing import List, Dict


NOTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "notion_search",
            "description": "Busca información en el workspace de Notion de Leo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Términos de búsqueda"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notion_fetch",
            "description": "Lee el contenido completo de una página de Notion",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "ID de la página de Notion"}
                },
                "required": ["page_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notion_create",
            "description": "Crea una nueva página en Notion (SIEMPRE pide confirmación antes)",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string", "description": "ID de la página padre"},
                    "title": {"type": "string", "description": "Título de la nueva página"},
                    "content": {"type": "string", "description": "Contenido de la página"}
                },
                "required": ["parent_id", "title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_app",
            "description": "Genera un plan de proyecto automático: busca en Notion, construye blueprint y planifica tareas. Úsala cuando el usuario describa una idea de app o proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "Descripción en lenguaje natural de la idea de app o proyecto"
                    }
                },
                "required": ["idea"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_plan",
            "description": "Ejecuta las tareas de un plan previamente generado con build_app. Necesita el plan_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "ID del plan a ejecutar (UUID)"
                    }
                },
                "required": ["plan_id"]
            }
        }
    }
]
