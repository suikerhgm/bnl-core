"""
NexusAgentes — Configuración centralizada (variables de entorno + clientes)
"""
import os
import logging
import sys
import httpx
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

# ── Logger ────────────────────────────────────
_logger = logging.getLogger("nexus")
_logger.setLevel(logging.INFO)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_ch.setFormatter(_fmt)
_logger.addHandler(_ch)
logger = _logger

# ── Tokens y claves ────────────────────────────
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")
API_KEY = os.getenv("API_KEY")

# ── Validaciones ──────────────────────────────
if not NOTION_TOKEN:
    raise ValueError(
        "NOTION_TOKEN no encontrado. "
        "Agrega NOTION_TOKEN=secret_xxx en tu archivo .env"
    )

if not API_KEY:
    raise ValueError(
        "API_KEY no encontrado. "
        "Agrega API_KEY=<clave-secreta> en tu archivo .env"
    )

# ── Cliente Notion ────────────────────────────
notion_client = Client(
    auth=NOTION_TOKEN,
    notion_version=NOTION_VERSION,
    client=httpx.Client(timeout=30.0),
)
