"""
NexusAgentes — Telegram Bot Runner (Polling)
============================================
Unico entrypoint del sistema. Conecta Telegram directamente
con conversation_orchestrator.process_message sin n8n.

Ejecucion:
    py -m app.main
"""
import logging
import os
import sys
from typing import Dict

from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -- Estados en memoria ---------------------------------------------
user_states: Dict[int, Dict] = {}

# -- Importar orquestador -------------------------------------------
from orchestrators.conversation_orchestrator import process_message


def main() -> None:
    """Inicia el bot de Telegram por polling."""

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN no esta configurado en .env")
        sys.exit(1)

    # Import tardio de PTB
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters

    app = Application.builder().token(token).build()

    async def handle_message(update: Update, context) -> None:
        """Maneja cada mensaje entrante."""
        if not update.message or not update.message.text:
            return

        chat_id = update.message.chat_id
        user_message = update.message.text

        logger.info("[%d] %s", chat_id, user_message[:100])

        # Estado del usuario
        if chat_id not in user_states:
            user_states[chat_id] = {"state": "IDLE"}
        state = user_states[chat_id]

        logger.info("🚨 CALLING process_message from main.py")

        try:
            response = await process_message(user_message, chat_id, state)
        except Exception as e:
            logger.error("Error en process_message: %s", e, exc_info=True)
            response = "Ocurrio un error interno. Intenta de nuevo."

        if response:
            try:
                await update.message.reply_text(
                    response,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning("Error al responder (Markdown): %s", e)
                try:
                    await update.message.reply_text(response)
                except Exception as e2:
                    logger.error("Error al responder (texto plano): %s", e2)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Nexus BNL iniciado - Escuchando mensajes por polling...")
    print("Bot activo. Presiona Ctrl+C para detener.")

    # PTB maneja su propio event loop internamente
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
