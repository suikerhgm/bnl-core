"""
Módulo de gateway para la API de Notion.
Contiene todas las funciones de comunicación con Notion.
"""
import os
import re
import logging
from typing import Dict, List, Optional
from difflib import SequenceMatcher

import httpx


# ── Logger ─────────────────────────────────────
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _ch = logging.StreamHandler()
    _ch.setLevel(logging.INFO)
    _fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)


# Credenciales
NOTION_TOKEN = os.getenv("NOTION_TOKEN")

# Bases de datos de conocimiento limpio/sucio
NOTION_DIRTY_DB_ID = os.getenv("NOTION_DIRTY_DB_ID")
NOTION_CLEAN_DB_ID = os.getenv("NOTION_CLEAN_DB_ID")
NOTION_TITLE_PROPERTY = os.getenv("NOTION_TITLE_PROPERTY", "title")


def _clean_page_id(page_id: str) -> Optional[str]:
    """
    Limpia y valida un ID de página de Notion.
    - Las IDs vienen como UUIDs de 36 caracteres con guiones
    - La IA a veces genera IDs sin guiones o con guiones en posiciones incorrectas
    - Retorna el ID limpio o None si es inválido
    """
    import re

    if not page_id:
        return None

    cleaned = page_id.strip()

    # Si parece una URL completa de Notion, extraer el ID
    if "notion.so/" in cleaned.lower():
        uuid_match = re.search(
            r'[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}',
            cleaned.lower()
        )
        if uuid_match:
            cleaned = uuid_match.group(0)

    # Estrategia 1: UUID con guiones
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if re.match(uuid_pattern, cleaned, re.IGNORECASE):
        return cleaned

    # Estrategia 2: 32 hex sin guiones → formatear
    hex_only = re.sub(r'[^0-9a-fA-F]', '', cleaned)
    if len(hex_only) >= 32:
        h = hex_only[:32].lower()
        result = f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
        logger.info(f"🔧 ID reconstruido: {page_id} → {result}")
        return result

    logger.warning(f"⚠️ No se pudo limpiar page_id: '{page_id}'")
    return None


async def notion_search(query: str) -> Dict:
    """Busca en Notion usando la API"""
    if not query or not query.strip():
        return {"error": "La consulta de búsqueda está vacía"}

    url = "https://api.notion.com/v1/search"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    data = {"query": query, "page_size": 10}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=30.0)
            if response.status_code == 200:
                return response.json()
            error_detail = response.json().get("message", "Error desconocido")
            logger.error(f"❌ Notion search error ({response.status_code}): {error_detail}")
            return {"error": f"Notion respondió con error: {error_detail}"}
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión con Notion search: {e}")
        return {"error": f"No se pudo conectar con Notion: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Error inesperado en notion_search: {e}", exc_info=True)
        return {"error": f"Error inesperado al buscar en Notion: {str(e)}"}


async def notion_fetch(page_id: str) -> Dict:
    """Obtiene el contenido de una página de Notion"""
    if not page_id or not page_id.strip():
        return {"error": "El ID de página está vacío. Por favor proporciona un ID válido de Notion."}

    cleaned_id = _clean_page_id(page_id)
    if cleaned_id != page_id:
        logger.info(f"🔧 ID de página limpiado: {page_id} → {cleaned_id}")
        page_id = cleaned_id

    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
            if response.status_code == 200:
                page_data = response.json()
                blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
                blocks_response = await client.get(blocks_url, headers=headers, timeout=30.0)
                if blocks_response.status_code == 200:
                    return {"page": page_data, "blocks": blocks_response.json()}
                logger.warning(f"⚠️ No se pudieron obtener bloques: {blocks_response.status_code}")
                return {"page": page_data, "blocks": {"error": "No se pudieron cargar los bloques"}, "partial": True}
            else:
                error_detail = response.json().get("message", "Error desconocido")
                logger.error(f"❌ Notion fetch error ({response.status_code}) para page_id={page_id}: {error_detail}")
                if response.status_code == 404:
                    return {"error": f"No se encontró la página con ID '{page_id}'. Verifica que el ID sea correcto."}
                elif response.status_code == 400:
                    return {"error": f"El ID de página '{page_id}' no es válido."}
                return {"error": f"Notion respondió con error ({response.status_code}): {error_detail}"}
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión con Notion fetch: {e}")
        return {"error": f"No se pudo conectar con Notion: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Error inesperado en notion_fetch: {e}", exc_info=True)
        return {"error": f"Error inesperado al leer la página de Notion: {str(e)}"}


def build_notion_blocks(title: str, content: str, summary: str) -> List[Dict]:
    """
    Construye bloques de Notion estructurados a partir del contenido.
    Evita problemas de límite de caracteres (2000+) dividiendo en chunks.
    """
    blocks = []

    # Heading 1 con el título
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": title}}]
        }
    })

    # Párrafo de resumen
    if summary:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": summary}}]
            }
        })

    # Divisor
    blocks.append({
        "object": "block",
        "type": "divider",
        "divider": {}
    })

    # Contenido principal dividido en chunks de ~1500 chars
    if content:
        chunk_size = 1500
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                }
            })

    return blocks


async def notion_create(database_id: str, properties: Dict, children: Optional[List] = None) -> Dict:
    """Crea una nueva página en una base de datos de Notion."""
    if not database_id or not database_id.strip():
        return {"error": "El ID de la base de datos está vacío."}
    if not properties:
        return {"error": "Las propiedades están vacías."}

    cleaned_id = _clean_page_id(database_id)
    if cleaned_id != database_id:
        database_id = cleaned_id

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    data = {
        "parent": {"database_id": database_id},
        "properties": properties
    }
    if children:
        data["children"] = children

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=30.0)
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Página creada en Notion DB: {database_id}")
                return result
            error_detail = response.json().get("message", "Error desconocido")
            logger.error(f"❌ Notion create error ({response.status_code}): {error_detail}")
            if response.status_code == 404:
                return {"error": f"No se encontró la base de datos con ID '{database_id}'."}
            elif response.status_code == 400:
                return {"error": f"Error al crear la página: {error_detail}."}
            return {"error": f"Notion respondió con error ({response.status_code}): {error_detail}"}
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión con Notion create: {e}")
        return {"error": f"No se pudo conectar con Notion: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Error inesperado en notion_create: {e}", exc_info=True)
        return {"error": f"Error inesperado al crear página en Notion: {str(e)}"}


async def notion_update(page_id: str, properties: Dict) -> Dict:
    """Actualiza las propiedades de una página existente en Notion."""
    if not page_id or not page_id.strip():
        return {"error": "El ID de página está vacío."}

    cleaned_id = _clean_page_id(page_id)
    if cleaned_id != page_id:
        page_id = cleaned_id

    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    data = {"properties": properties}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, headers=headers, json=data, timeout=30.0)
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Página actualizada en Notion: {page_id}")
                return result
            error_detail = response.json().get("message", "Error desconocido")
            logger.error(f"❌ Notion update error ({response.status_code}): {error_detail}")
            return {"error": f"Notion respondió con error ({response.status_code}): {error_detail}"}
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión con Notion update: {e}")
        return {"error": f"No se pudo conectar con Notion: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ Error inesperado en notion_update: {e}", exc_info=True)
        return {"error": f"Error inesperado al actualizar página en Notion: {str(e)}"}


async def _notion_query_database(database_id: str, query: str) -> Dict:
    """
    Busca en una base de datos específica de Notion por título.
    """
    if not database_id:
        logger.warning("⚠️ No se proporcionó database_id para búsqueda en base de datos")
        return {"results": []}

    url = f"https://api.notion.com/v1/databases/{_clean_page_id(database_id)}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    data = {
        "filter": {
            "property": NOTION_TITLE_PROPERTY,
            "title": {"contains": query}
        },
        "page_size": 10
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=30.0)
            if response.status_code == 200:
                return response.json()
            logger.error(f"❌ Database query error ({response.status_code}): {response.text[:200]}")
            return {"results": []}
    except Exception as e:
        logger.error(f"❌ Error en _notion_query_database: {e}")
        return {"results": []}


def _fuzzy_match_title(title_a: str, title_b: str) -> float:
    """
    Comparación fuzzy entre dos títulos usando SequenceMatcher.
    Retorna un score entre 0.0 y 1.0.
    """
    if not title_a or not title_b:
        return 0.0
    return SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()
