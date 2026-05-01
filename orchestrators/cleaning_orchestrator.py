"""
Orquestador del flujo de limpieza de Notion.
Maneja los modos: searching, reviewing, confirm, APPLY, saved.
"""
import json
import logging
from typing import Dict, List, Optional

from core.state_manager import save_states
from core.ai_cascade import call_ai_with_fallback
from core.notion_gateway import (
    notion_search,
    notion_fetch,
    notion_create,
    notion_update,
    _notion_query_database,
    _fuzzy_match_title,
    build_notion_blocks,
    NOTION_CLEAN_DB_ID
)
from app.services.notion_cleaner_agent import NotionCleanerAgent

cleaner = NotionCleanerAgent()
logger = logging.getLogger(__name__)


# ===== SISTEMA DE APLICACIÓN DE LIMPIEZA =====

async def apply_cleaning_result(clean_result: dict, user_feedback: str, source_pages: List[Dict]) -> dict:
    """
    Convierte el análisis + feedback del usuario en conocimiento estructurado
    persistente en la base de datos limpia de Notion.

    Steps:
    1. Merge analysis + feedback using AI → structured JSON
    2. Duplicate detection in NOTION_CLEAN_DB_ID (fuzzy match ≥ 0.85)
    3. Create or update in clean DB
    4. Return result
    """
    logger.info("🧹 apply_cleaning_result: iniciando proceso...")

    # ── STEP 1: Merge analysis + feedback via AI ──────────
    current_analysis = clean_result.get("analysis", {})
    source_ids = [p.get("id", "") for p in source_pages if p.get("id")]

    merge_messages = [
        {
            "role": "system",
            "content": (
                "Eres un arquitecto de conocimiento. Recibes un análisis de Notion "
                "y feedback del usuario. Debes generar un objeto JSON final con la "
                "estructura limpia y organizada. Responde SOLO con JSON válido, sin "
                "markdown ni texto adicional."
            )
        },
        {
            "role": "user",
            "content": f"""
Analiza este contenido y el feedback del usuario.

ANÁLISIS ACTUAL:
{json.dumps(current_analysis, ensure_ascii=False, indent=2)}

FEEDBACK DEL USUARIO:
{user_feedback}

PAGES FUENTE (IDs):
{json.dumps(source_ids, ensure_ascii=False)}

Genera un objeto JSON final con esta estructura exacta:
{{
  "title": "Título descriptivo del conocimiento",
  "type": "concept | system | app | idea",
  "summary": "Resumen de 1-2 párrafos",
  "content": "Contenido completo y estructurado",
  "tags": ["tag1", "tag2"],
  "source_pages": {json.dumps(source_ids, ensure_ascii=False)},
  "version": 1
}}
"""
        }
    ]

    merge_response, _ = await call_ai_with_fallback(merge_messages)

    # Parsear JSON de la respuesta
    try:
        raw_text = merge_response["content"]
        # Limpiar posibles wrappers de markdown
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
        structured = json.loads(raw_text)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"❌ Error parseando respuesta JSON de IA: {e}")
        logger.debug(f"Raw response: {merge_response.get('content', '')}")
        return {
            "status": "error",
            "error": f"No se pudo generar la estructura final: {str(e)}"
        }

    title = structured.get("title", "Sin título")
    content_type = structured.get("type", "concept")

    # ── STEP 2: Duplicate detection ──────────────────────
    status = "created"
    existing_id = None
    duplicates_found = 0
    version = 1

    if NOTION_CLEAN_DB_ID:
        logger.info(f"🔍 Buscando duplicados en clean DB para título: '{title}'")
        search_result = await _notion_query_database(NOTION_CLEAN_DB_ID, title)
        existing_pages = search_result.get("results", [])

        for page in existing_pages:
            page_title = ""
            try:
                title_prop = page.get("properties", {}).get("title", {})
                page_title = title_prop.get("title", [{}])[0].get("text", {}).get("content", "")
            except (IndexError, KeyError, AttributeError):
                pass

            if page_title:
                score = _fuzzy_match_title(title, page_title)
                logger.info(f"   Fuzzy match '{title}' vs '{page_title}': {score:.2f}")
                if score >= 0.85:
                    existing_id = page.get("id")
                    duplicates_found += 1

                    # Obtener versión actual
                    try:
                        existing_version = page.get("properties", {}).get("version", {}).get("number", 0)
                        version = (existing_version or 0) + 1
                    except (KeyError, TypeError):
                        version = 2

                    structured["version"] = version
                    status = "updated"
                    logger.info(f"✅ Duplicado encontrado (score={score:.2f}): {page_title} → actualizando v{version}")
                    break

    # ── STEP 3: Real duplicate merge (when updating) ────
    if existing_id and NOTION_CLEAN_DB_ID:
        logger.info(f"🔄 Duplicado encontrado — haciendo merge de contenido...")
        existing_data = await notion_fetch(existing_id)

        # Extraer contenido viejo del fetch
        old_content = ""
        if "error" not in existing_data:
            try:
                blocks = existing_data.get("blocks", {}).get("results", [])
                old_text_parts = []
                for block in blocks:
                    btype = block.get("type", "")
                    rtf = block.get(btype, {}).get("rich_text", [])
                    for rt in rtf:
                        old_text_parts.append(rt.get("text", {}).get("content", ""))
                old_content = "\n".join(old_text_parts)
            except Exception as e:
                logger.warning(f"⚠️ No se pudo extraer contenido viejo: {e}")

        if old_content:
            merge_prompt = [
                {
                    "role": "system",
                    "content": "Eres un arquitecto de conocimiento. Fusiona información sin perder datos."
                },
                {
                    "role": "user",
                    "content": f"""
CONTENIDO VIEJO (ya existe en Notion):
{old_content}

CONTENIDO NUEVO (de esta iteración):
{structured.get('content', '')}

Fusiona ambos en una versión unificada sin duplicar información.
Devuelve SOLO el texto fusionado, sin markdown.
"""
                }
            ]
            merged_response, _ = await call_ai_with_fallback(merge_prompt)
            merged_content = merged_response.get("content", structured.get("content", ""))
            structured["content"] = merged_content
            logger.info("✅ Contenido fusionado exitosamente")

    # ── STEP 4: Build properties (metadata only) ────────
    properties = {
        "title": {"title": [{"text": {"content": title}}]},
        "type": {"select": {"name": content_type}},
        "summary": {"rich_text": [{"text": {"content": structured.get("summary", "")}}]},
        "version": {"number": version},
        "tags": {"multi_select": [{"name": t} for t in structured.get("tags", [])]},
    }

    # ── STEP 5: Build children blocks (actual content) ──
    children = build_notion_blocks(title, structured.get("content", ""), structured.get("summary", ""))

    # ── STEP 6: Write to Notion ─────────────────────────
    notion_result = None

    if existing_id and NOTION_CLEAN_DB_ID:
        # Update: only properties (Notion API limitation — can't replace blocks)
        logger.info(f"📝 Actualizando página existente: {existing_id} (v{version})")
        notion_result = await notion_update(existing_id, properties)

    elif NOTION_CLEAN_DB_ID:
        # Create new page in clean DB with correct schema
        logger.info(f"📝 Creando nueva página en clean DB: '{title}'")
        notion_result = await notion_create(NOTION_CLEAN_DB_ID, properties, children)

    else:
        logger.warning("⚠️ NOTION_CLEAN_DB_ID no configurado — no se escribió a Notion")
        notion_result = {"error": "NOTION_CLEAN_DB_ID no está configurado en .env"}

    notion_id = ""
    if notion_result and not notion_result.get("error"):
        notion_id = notion_result.get("id", existing_id or "")

    logger.info(f"✅ apply_cleaning_result completado: status={status}, title='{title}', version={version}")

    return {
        "status": status,
        "title": title,
        "type": content_type,
        "version": version,
        "notion_id": notion_id,
        "duplicates_found": duplicates_found
    }


async def handle_cleaning_flow(user_message: str, chat_id: int, state: dict) -> Optional[str]:
    """
    Maneja el flujo de limpieza de Notion (NOTION_CLEANING).
    Retorna None si el estado no es NOTION_CLEANING.
    Retorna la respuesta del bot si se procesó algún modo.
    """
    if state.get("state") != "NOTION_CLEANING":
        return None

    # ── searching mode ──────────────────────────────
    if state.get("mode") == "searching":
        result = await notion_search(user_message)

        state["pages_pending"] = result.get("results", [])
        state["mode"] = "reviewing"
        save_states()

        return f"Encontré {len(state['pages_pending'])} páginas. Vamos a revisar la primera."

    # ── reviewing mode ──────────────────────────────
    if state.get("mode") == "reviewing":

        pages = state["pages_pending"][:5]

        analysis = await cleaner.analyze_pages(pages)

        state["mode"] = "confirm"
        state["analysis"] = analysis
        save_states()

        return f"""
🧠 Análisis:

{analysis['analysis']}

¿Te gusta esta estructura o quieres ajustarla?
"""

    # ── confirm mode ────────────────────────────────
    if state.get("mode") == "confirm":

        feedback = user_message

        # ── Detectar confirmación explícita ──────────────
        if feedback.lower().strip() in ["si", "sí", "yes", "dale", "me gusta"]:

            state["mode"] = "APPLY"
            save_states()

            pages = state.get("pages_pending", [])
            analysis = state.get("analysis", {})

            result = await apply_cleaning_result(analysis, feedback, pages)

            if result.get("status") == "error":
                state["mode"] = "confirm"
                save_states()
                return f"⚠️ Error al guardar: {result.get('error')}"

            state["mode"] = "saved"
            state["cleaning_result"] = result
            save_states()

            sources_count = len(pages)
            emoji_status = "✅" if result["status"] == "created" else "🔄"

            return f"""{emoji_status} Saved to Notion Clean

**Title:** {result['title']}
**Type:** {result['type']}
**Version:** {result['version']}
**Sources merged:** {sources_count} páginas
**Duplicates found:** {result['duplicates_found']}

Do you want to continue cleaning or build something from this?
"""

        # ── Refinamiento (cualquier otro mensaje) ────────
        messages = [
            {
                "role": "system",
                "content": "Eres un arquitecto refinando estructura de conocimiento."
            },
            {
                "role": "user",
                "content": f"""
Estructura actual:
{state.get("analysis")}

Feedback del usuario:
{feedback}

Devuelve versión mejorada.
"""
            }
        ]

        response, _ = await call_ai_with_fallback(messages)

        return f"🧠 Versión refinada:\n\n{response['content']}"

    return None
