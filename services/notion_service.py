"""
NexusAgentes — Servicio de Notion
Provee funciones: notion_search, notion_fetch, notion_create
"""
from typing import List, Optional

from app.config import notion_client, logger


# ──────────────────────────────────────────────
# AUXILIARES
# ──────────────────────────────────────────────


def _extract_page_title(page: dict) -> str:
    """Extrae el titulo de una pagina de Notion desde sus propiedades."""
    try:
        title_prop = page.get("properties", {}).get("title", {})
        title_list = title_prop.get("title", [])
        return "".join([t.get("plain_text", "") for t in title_list])
    except Exception:
        return "Untitled"


def _block_to_markdown(block: dict) -> Optional[str]:
    """Convierte un bloque de Notion a texto Markdown."""
    block_type = block.get("type", "unsupported")
    block_data = block.get(block_type, {})

    rich_text = block_data.get("rich_text", [])
    text_content = "".join([t.get("plain_text", "") for t in rich_text])

    type_map = {
        "paragraph": lambda: f"{text_content}\n\n",
        "heading_1": lambda: f"# {text_content}\n\n",
        "heading_2": lambda: f"## {text_content}\n\n",
        "heading_3": lambda: f"### {text_content}\n\n",
        "bulleted_list_item": lambda: f"- {text_content}\n",
        "numbered_list_item": lambda: f"1. {text_content}\n",
        "to_do": lambda: (
            f"- [{'x' if block_data.get('checked', False) else ' '}] "
            f"{text_content}\n"
        ),
        "code": lambda: (
            f"```{block_data.get('language', '')}\n"
            f"{text_content}\n```\n\n"
        ),
        "quote": lambda: f"> {text_content}\n\n",
        "divider": lambda: "---\n\n",
        "callout": lambda: f"> * {text_content}\n\n",
        "image": lambda: (
            f"![{block_data.get('caption', [{}])[0].get('plain_text', 'image')}]"
            f"({block_data.get('external', {}).get('url', '') or block_data.get('file', {}).get('url', '')})\n\n"
        ),
        "bookmark": lambda: f"[{text_content}]({block_data.get('url', '')})\n\n",
        "toggle": lambda: f"<details>\n<summary>{text_content}</summary>\n\n(contenido colapsado)\n</details>\n\n",
    }

    handler = type_map.get(block_type)
    if handler:
        return handler()
    if text_content:
        return f"{text_content}\n\n"
    return None


def _get_all_blocks(page_id: str) -> List[dict]:
    """Obtiene TODOS los bloques de una pagina, paginando automaticamente."""
    all_blocks = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion_client.blocks.children.list(
            block_id=page_id,
            start_cursor=start_cursor,
            page_size=100,
        )
        all_blocks.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    return all_blocks


def _blocks_to_markdown(blocks: List[dict]) -> str:
    """Convierte una lista de bloques de Notion a Markdown completo."""
    parts = []
    for block in blocks:
        md = _block_to_markdown(block)
        if md:
            parts.append(md)
    return "".join(parts)


def _markdown_to_notion_blocks(markdown_text: str) -> List[dict]:
    """Convierte texto Markdown a bloques de Notion."""
    lines = markdown_text.split("\n")
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            text = stripped[2:]
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            })
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            text = stripped[3:]
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            })
        elif stripped.startswith("### "):
            text = stripped[4:]
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            })
        elif stripped == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped.startswith("- "):
            text = stripped[2:]
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            })
        elif (
            len(stripped) > 2
            and stripped[0].isdigit()
            and stripped[1] == "."
            and stripped[2] == " "
        ):
            text = stripped[3:]
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": stripped}}]
                },
            })

        i += 1

    return blocks


# ──────────────────────────────────────────────
# FUNCIONES PUBLICAS
# ──────────────────────────────────────────────


def notion_search(query: str) -> List[dict]:
    """
    Busca paginas en Notion por termino de busqueda.
    Retorna maximo 10 resultados, solo paginas (no databases).
    """
    logger.info(f"Busqueda en Notion: query='{query}'")

    response = notion_client.search(
        query=query,
        filter={"property": "object", "value": "page"},
        page_size=10,
        sort={"direction": "descending", "timestamp": "last_edited_time"},
    )

    results = response.get("results", [])
    pages = []

    for page in results:
        page_id = page.get("id", "").replace("-", "")
        title = _extract_page_title(page)
        url = page.get("url", f"https://www.notion.so/{page_id}")

        pages.append({
            "id": page_id,
            "title": title,
            "url": url,
            "type": "page",
        })

    logger.info(f"Search completado: {len(pages)} resultados encontrados")
    return pages


def notion_fetch(page_id: str) -> dict:
    """
    Lee el contenido completo de una pagina de Notion.
    Retorna metadata + contenido en Markdown.
    """
    logger.info(f"Leyendo pagina: page_id={page_id}")

    clean_id = page_id.replace("-", "")

    page = notion_client.pages.retrieve(page_id=clean_id)
    logger.info(f"Metadata obtenida para pagina: {page.get('id', 'unknown')}")

    blocks = _get_all_blocks(clean_id)
    logger.info(f"Bloques obtenidos: {len(blocks)}")

    title = _extract_page_title(page)
    url = page.get("url", f"https://www.notion.so/{clean_id}")
    created_time = page.get("created_time", "")
    last_edited_time = page.get("last_edited_time", "")

    content = _blocks_to_markdown(blocks)

    return {
        "id": clean_id,
        "title": title,
        "url": url,
        "content": content,
        "created_time": created_time,
        "last_edited_time": last_edited_time,
    }


def notion_create(parent_id: str, title: str, content: str) -> dict:
    """
    Crea una nueva pagina en Notion dentro de una pagina padre.
    Convierte el contenido Markdown a bloques de Notion.
    """
    logger.info(f"Creando pagina en Notion: title='{title}' | parent={parent_id}")

    clean_parent_id = parent_id.replace("-", "")
    children_blocks = _markdown_to_notion_blocks(content)
    logger.info(f"Markdown convertido a {len(children_blocks)} bloques")

    new_page = notion_client.pages.create(
        parent={"type": "page_id", "page_id": clean_parent_id},
        properties={
            "title": {
                "title": [
                    {"type": "text", "text": {"content": title}},
                ]
            }
        },
        children=children_blocks,
    )

    new_id = new_page.get("id", "").replace("-", "")
    new_url = new_page.get("url", f"https://www.notion.so/{new_id}")

    logger.info(f"Pagina creada exitosamente: {new_url}")
    return {
        "id": new_id,
        "url": new_url,
        "title": title,
        "status": "created",
    }
