"""
🤖 NexusAgentes — Servicio de Telegram (lógica pura, sin servidor)
Contiene: API cascade, fallback multi-IA, funciones Notion, build_app, process_message.

Stack:
- 8 APIs en cascada (Groq x3, Gemini x2, DeepSeek x2, OpenRouter x1)
- Notion API
- FastAPI backend (vía httpx)
"""
import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from core.state_manager import (
    get_chat_state,
    save_states,
    chat_states,
    save_short_memory,
    clean_memory
)
from core.ai_cascade import (
    call_ai_with_fallback,
    NEXUS_BNL_SYSTEM_PROMPT,
    extract_ai_content,
    AIProvider,
    AttrDict,
    API_CASCADE,
    current_api_index
)
from core.notion_gateway import (
    notion_search,
    notion_fetch,
    notion_create,
    notion_update,
    _notion_query_database,
    _fuzzy_match_title,
    build_notion_blocks,
    NOTION_DIRTY_DB_ID,
    NOTION_CLEAN_DB_ID,
    NOTION_TITLE_PROPERTY
)
from core.backend_client import call_build_app, call_execute_plan
from core.formatters import _format_plan_result, _format_execution_result
from core.tools import NOTION_TOOLS
from orchestrators.conversation_orchestrator import process_message

import httpx
from dotenv import load_dotenv


load_dotenv()

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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Validaciones
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN no está configurado en .env")
if not any(config["api_key"] for config in API_CASCADE):
    raise ValueError("❌ No hay ninguna API key configurada en .env")


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Envía un mensaje a Telegram con manejo de errores."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if not text or not text.strip():
        text = "⚠️ No hubo respuesta disponible."
    if len(text) > 4000:
        text = text[:3997] + "..."

    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    if text.count("*") % 2 != 0 or text.count("`") % 2 != 0 or text.count("_") % 2 != 0:
        logger.warning("⚠️ Markdown mal formado, enviando sin parse_mode")
        data.pop("parse_mode", None)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, timeout=30.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info(f"✅ Mensaje enviado a {chat_id}")
                    return True
                error_desc = result.get('description', 'sin descripción')
                logger.warning(f"⚠️ Telegram rechazó mensaje: {error_desc}")
                if "parse_mode" in error_desc or "can't parse" in error_desc.lower():
                    logger.info("🔄 Reintentando sin parse_mode...")
                    data.pop("parse_mode", None)
                    retry = await client.post(url, json=data, timeout=30.0)
                    if retry.status_code == 200 and retry.json().get("ok"):
                        logger.info(f"✅ Mensaje enviado a {chat_id} (sin parse_mode)")
                        return True
                return False
            logger.error(f"❌ Error {response.status_code} al enviar mensaje a {chat_id}: {response.text[:200]}")
            return False
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión al enviar mensaje a {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error inesperado al enviar mensaje a {chat_id}: {e}", exc_info=True)
        return False


# ===== HANDLER PARA WEBHOOK (PURA LÓGICA) =====

async def handle_telegram_update(update: dict) -> None:
    """
    Procesa un update entrante de Telegram.
    Extrae chat_id y mensaje, lo procesa con process_message()
    y envía la respuesta con send_telegram_message().

    Esta función es la interfaz entre cualquier servidor (FastAPI, Flask, etc.)
    y la lógica del bot. No depende de ningún framework.
    """
    if "message" not in update:
        logger.info("⏭️ No message in update, skipping")
        return

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_message = message.get("text", "")

    if not user_message:
        logger.info("⏭️ Empty message, skipping")
        return

    logger.info(f"💬 Mensaje de {chat_id}: {user_message}")

    state = get_chat_state(chat_id)
    response_text = await process_message(user_message, chat_id, state)
    await send_telegram_message(chat_id, response_text)
