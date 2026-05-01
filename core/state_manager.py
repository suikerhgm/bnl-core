"""
Módulo de gestión de estado para el bot NexusAgentes.
Maneja persistencia de estados de chat y sistema de memoria multicapa.
"""
import os
import json
import logging
from typing import Dict
from datetime import datetime, timedelta

# Persistencia de estados en disco
STATE_FILE = "chat_states.json"


def load_states() -> Dict[int, Dict]:
    """Carga los estados desde el archivo JSON en disco."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Convertir claves string a int (json serializa claves numéricas como string)
            return {int(k): v for k, v in raw.items()}
        except Exception as e:
            logging.getLogger(__name__).warning(f"⚠️ No se pudo cargar {STATE_FILE}: {e}")
    return {}


def save_states() -> None:
    """Guarda los estados en el archivo JSON en disco."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_states, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.getLogger(__name__).error(f"❌ No se pudo guardar {STATE_FILE}: {e}")


chat_states = load_states()


def get_chat_state(chat_id: int) -> Dict:
    """Obtiene el estado de un chat, creándolo si no existe."""
    if chat_id not in chat_states:
        chat_states[chat_id] = {"state": "IDLE"}
        save_states()
    return chat_states[chat_id]



# ===== SISTEMA DE MEMORIA MULTICAPA =====

memory = {
    "short": {},   # 12 horas
    "medium": {},  # 7 días
    "long": {}     # permanente (Notion después)
}


def save_short_memory(chat_id, message):
    """Guarda un mensaje en la memoria de corto plazo."""
    memory["short"][chat_id] = {
        "message": message,
        "timestamp": datetime.now().isoformat()
    }


def clean_memory():
    """Transfiere memorias antiguas de corto a mediano plazo."""
    now = datetime.now()

    for chat_id, data in list(memory["short"].items()):
        if now - datetime.fromisoformat(data["timestamp"]) > timedelta(hours=12):
            memory["medium"][chat_id] = data
            del memory["short"][chat_id]
