"""
Módulo de cascada de APIs de IA para NexusAgentes.
Maneja el fallback multi-IA (Groq, Gemini, DeepSeek, OpenRouter).
"""
import os
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

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


def extract_ai_content(resp):
    """
    Extrae el contenido textual de la respuesta de cualquier proveedor de IA
    de forma segura, sin importar si viene como AttrDict o dict plano.
    Groq a veces omite el campo 'content' cuando solo devuelve tool_calls.
    """
    try:
        return resp.choices[0].message.content
    except Exception:
        pass
    try:
        return resp["choices"][0]["message"]["content"]
    except Exception:
        pass
    try:
        return resp.choices[0].message.get("content")
    except Exception:
        pass
    return ""


# ===== CONFIGURACIÓN DE APIs =====

class AIProvider(Enum):
    """Proveedores de IA disponibles"""
    GROQ_1 = "groq_1"
    GROQ_2 = "groq_2"
    GROQ_3 = "groq_3"
    GEMINI_1 = "gemini_1"
    GEMINI_2 = "gemini_2"
    DEEPSEEK_1 = "deepseek_1"
    DEEPSEEK_2 = "deepseek_2"
    OPENROUTER = "openrouter"


class AttrDict:
    """
    Convierte un dict anidado en un objeto con acceso por atributos.
    Permite que assistant_message.content, tc.id, tc.function.name, etc.
    funcionen tanto con objetos Pydantic (Groq) como con dicts (DeepSeek/OpenRouter/Gemini).
    """
    def __init__(self, d):
        self._data = d

    def __getattr__(self, name):
        if name == "_data":
            return object.__getattribute__(self, "_data")
        if name in self._data:
            value = self._data[name]
            if isinstance(value, dict):
                return AttrDict(value)
            elif isinstance(value, list):
                return [
                    AttrDict(item) if isinstance(item, dict) else item
                    for item in value
                ]
            return value
        raise AttributeError(f"'AttrDict' object has no attribute '{name}'")

    def __contains__(self, item):
        return item in self._data

    def __bool__(self):
        return bool(self._data)

    def __repr__(self):
        return repr(self._data)


# Configuración de cascada de APIs (orden de prioridad)
API_CASCADE = [
    {
        "provider": AIProvider.GROQ_1,
        "api_key": os.getenv("GROQ_API_KEY_1"),
        "model": "llama-3.3-70b-versatile",
        "name": "Groq Llama 3.3 70B (Principal)",
        "max_tokens": 2000
    },
    {
        "provider": AIProvider.GROQ_2,
        "api_key": os.getenv("GROQ_API_KEY_2"),
        "model": "llama-3.3-70b-versatile",
        "name": "Groq Llama 3.3 70B (Backup 1)",
        "max_tokens": 2000
    },
    {
        "provider": AIProvider.GEMINI_1,
        "api_key": os.getenv("GEMINI_API_KEY_1"),
        "model": "gemini-1.5-flash",
        "name": "Google Gemini 1.5 Flash",
        "max_tokens": 8000
    },
    {
        "provider": AIProvider.GROQ_3,
        "api_key": os.getenv("GROQ_API_KEY_3"),
        "model": "llama-3.1-8b-instant",
        "name": "Groq Llama 3.1 8B (Rápido)",
        "max_tokens": 2000
    },
    {
        "provider": AIProvider.DEEPSEEK_1,
        "api_key": os.getenv("DEEPSEEK_API_KEY_1"),
        "model": "deepseek-chat",
        "name": "DeepSeek Chat (Principal)",
        "max_tokens": 4000
    },
    {
        "provider": AIProvider.GEMINI_2,
        "api_key": os.getenv("GEMINI_API_KEY_2"),
        "model": "gemini-1.5-flash",
        "name": "Google Gemini 1.5 Flash (Backup)",
        "max_tokens": 8000
    },
    {
        "provider": AIProvider.DEEPSEEK_2,
        "api_key": os.getenv("DEEPSEEK_API_KEY_2"),
        "model": "deepseek-chat",
        "name": "DeepSeek Chat (Backup)",
        "max_tokens": 4000
    },
    {
        "provider": AIProvider.OPENROUTER,
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "name": "OpenRouter Llama 3.1 8B (Último recurso)",
        "max_tokens": 2000
    }
]

# Estado global: qué API estamos usando actualmente
current_api_index = 0


# ===== SYSTEM PROMPT =====

NEXUS_BNL_SYSTEM_PROMPT = """# Identidad

Eres **Nexus BNL**, una agencia autónoma de desarrollo IA.

## Personalidad
- Profesional, directo, sin rodeos
- Eficiente y orientado a resultados
- Obsesivo con la organización (El Geómetra)
- Paranoico con seguridad (El Guardián)
- Siempre pides aprobación en acciones críticas

## Reglas de oro
1. **Reporta resultados** con links
2. **NUNCA elimines nada** sin aprobación explícita
3. **SIEMPRE incluye links** a páginas de Notion
4. **Resumen antes de ejecutar** acciones críticas

## Herramientas disponibles
Tienes acceso a Notion para:
- `notion_search`: Buscar información en el workspace de Leo
- `notion_fetch`: Leer el contenido completo de una página
- `notion_create`: Crear nuevas páginas con contenido

## Ejemplo de conversación

Leo: "Busca info sobre ÉLITE"

Tú: 
"Encontré 3 páginas sobre ÉLITE:

1. **MAESTRO — Cerebro del Proyecto** 
   https://notion.so/...

2. **Sistema de Progresión v3.0**
   https://notion.so/...

3. **El Código del Oro v14.0**
   https://notion.so/...

¿Qué página quieres que abra?"

## SISTEMA DE CONSTRUCCIÓN DE APPS (build_app)
Tienes acceso a `build_app` para crear automáticamente un plan de proyecto.
Cuando el usuario mencione una idea de app, proyecto, o quiera construir algo:
- Usa `build_app` con su descripción como `idea`
- Reporta el `plan_id`, el blueprint y las tareas generadas
- Si el usuario dice "ejecutar {plan_id}" o similar, usa `execute_plan`

## IMPORTANTE
- SIEMPRE resume antes de ejecutar
- NUNCA asumas — pide confirmación
- SIEMPRE incluye links completos de Notion
- Sé breve y directo
"""


# ===== SISTEMA DE FALLBACK MULTI-API =====

async def call_ai_with_fallback(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict]] = None
) -> Tuple[Dict, int]:
    """
    Llama a las APIs de IA en cascada hasta que una funcione.
    Retorna: (response, api_index_used)
    """
    global current_api_index

    for attempt_index in range(current_api_index, len(API_CASCADE)):
        config = API_CASCADE[attempt_index]
        if not config["api_key"]:
            logger.warning(f"⏭️ {config['name']}: Sin API key, saltando")
            continue
        try:
            logger.info(f"🔄 Intentando con: {config['name']}")
            provider = config["provider"]

            if provider in (AIProvider.GROQ_1, AIProvider.GROQ_2, AIProvider.GROQ_3):
                response = await call_groq(config, messages, tools)
            elif provider in (AIProvider.GEMINI_1, AIProvider.GEMINI_2):
                response = await call_gemini(config, messages, tools)
            elif provider in (AIProvider.DEEPSEEK_1, AIProvider.DEEPSEEK_2):
                response = await call_deepseek(config, messages, tools)
            elif provider == AIProvider.OPENROUTER:
                response = await call_openrouter(config, messages, tools)
            else:
                continue

            current_api_index = attempt_index
            logger.info(f"✅ Éxito con: {config['name']}")
            return {
                "content": extract_ai_content(response),
                "raw": response,
                "provider": config["name"]
            }, attempt_index


        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate limit" in error_msg.lower():
                logger.warning(f"⚠️ {config['name']}: Rate limit, probando siguiente...")
                continue
            logger.error(f"❌ {config['name']}: Error {error_msg}")
            continue

    raise Exception("❌ Todas las APIs fallaron. Por favor espera unos minutos e intenta de nuevo.")


async def call_groq(config: Dict, messages: List[Dict], tools: Optional[List[Dict]]) -> Dict:
    """Llama a Groq API usando httpx."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    data = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": config["max_tokens"]
    }
    if tools:
        data["tools"] = tools
        data["tool_choice"] = "auto"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data, timeout=30.0)
        if response.status_code == 429:
            raise Exception("429 Too Many Requests - rate limit exceeded")
        response.raise_for_status()
        return AttrDict(response.json())


async def call_gemini(config: Dict, messages: List[Dict], tools: Optional[List[Dict]]) -> Dict:
    """Llama a Gemini API a través de su endpoint REST."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config['model']}:generateContent"
    gemini_contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    params = {"key": config["api_key"]}
    data = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": config["max_tokens"]
        }
    }
    if tools:
        gemini_tools = []
        for tool in tools:
            if tool["type"] == "function":
                gemini_tools.append({"functionDeclarations": [tool["function"]]})
        if gemini_tools:
            data["tools"] = gemini_tools

    async with httpx.AsyncClient() as client:
        response = await client.post(url, params=params, json=data, timeout=60.0)
        response.raise_for_status()
        result = response.json()

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        text = "Sin respuesta de Gemini"

    return AttrDict({
        "choices": [AttrDict({
            "message": AttrDict({"role": "assistant", "content": text})
        })]
    })


async def call_deepseek(config: Dict, messages: List[Dict], tools: Optional[List[Dict]]) -> Dict:
    """Llama a DeepSeek API (compatible con OpenAI)."""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    data = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": config["max_tokens"],
        "temperature": 0.7
    }
    if tools:
        data["tools"] = tools
        data["tool_choice"] = "auto"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data, timeout=60.0)
        response.raise_for_status()
        return AttrDict(response.json())


async def call_openrouter(config: Dict, messages: List[Dict], tools: Optional[List[Dict]]) -> Dict:
    """Llama a OpenRouter API."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nexus-bnl.app",
        "X-Title": "Nexus BNL Bot"
    }
    data = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": config["max_tokens"],
        "temperature": 0.7
    }
    if tools:
        data["tools"] = tools

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data, timeout=60.0)
        response.raise_for_status()
        return AttrDict(response.json())
