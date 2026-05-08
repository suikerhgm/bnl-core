# 🤖 Nexus BNL v2.0 — Bot de Telegram con Fallback Multi-API

Agencia autónoma de desarrollo IA con sistema de **8 APIs en cascada** para máxima disponibilidad.

## Stack

- **Telegram Bot API** — Interfaz de usuario
- **8 APIs de IA en cascada** — Groq x3, Gemini x2, DeepSeek x2, OpenRouter x1
- **Notion API** — Base de conocimiento
- **FastAPI** — Backend Python

## Arquitectura

```
Usuario (Telegram) → FastAPI Webhook → Sistema de Fallback Multi-API → Notion API
                                          │
                                          ├─ 🟢 Groq 1 (Principal)
                                          ├─ 🟢 Groq 2 (Backup)
                                          ├─ 🔵 Gemini 1
                                          ├─ 🟢 Groq 3 (Rápido)
                                          ├─ 🟠 DeepSeek 1
                                          ├─ 🔵 Gemini 2
                                          ├─ 🟠 DeepSeek 2
                                          └─ 🔴 OpenRouter (Último recurso)
```

## Setup

### 1. Clonar y configurar

```bash
git clone <repo>
cd NexusAgentes
cp .env.example .env
```

### 2. Editar `.env`

Completa todas las API keys en `.env`. Mínimo necesitas:

```env
TELEGRAM_BOT_TOKEN=tu_token
NOTION_TOKEN=tu_token_notion
GROQ_API_KEY_1=tu_groq_key
```

> **Nota:** El sistema funciona aunque solo tengas 1 API key configurada. Mientras más tengas, más resiliente será.

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Arrancar el bot

```bash
uvicorn nexus_bot:app --host 0.0.0.0 --port 8001
```

### 5. Configurar webhook de Telegram

```bash
curl -X POST http://localhost:8001/set-webhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tu-dominio.com/webhook"}'
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Health check + estado del bot |
| `POST` | `/webhook` | Webhook de Telegram |
| `POST` | `/set-webhook` | Configurar URL del webhook |
| `GET` | `/webhook-info` | Info del webhook actual |
| `GET` | `/api-status` | Estado detallado de todas las APIs |

### Ejemplo: Health Check

```bash
curl http://localhost:8001/
```

Respuesta:
```json
{
  "status": "✅ Nexus BNL Bot v2.0 activo",
  "timestamp": "2026-04-25T18:00:00",
  "bot": "@nexusagentes_bot",
  "apis_configured": 8,
  "current_api": "Groq Llama 3.3 70B (Principal)"
}
```

### Ejemplo: Estado de APIs

```bash
curl http://localhost:8001/api-status
```

Respuesta:
```json
{
  "current_index": 0,
  "current_api": "Groq Llama 3.3 70B (Principal)",
  "cascade": [
    {"index": 0, "name": "Groq Llama 3.3 70B (Principal)", "configured": true},
    {"index": 1, "name": "Groq Llama 3.3 70B (Backup 1)", "configured": true},
    ...
  ]
}
```

## Sistema de Fallback Multi-API

### Orden de prioridad

| # | Proveedor | Modelo | Tokens | Propósito |
|---|-----------|--------|--------|-----------|
| 1 | 🟢 **Groq 1** | `llama-3.3-70b-versatile` | 2,000 | Principal |
| 2 | 🟢 **Groq 2** | `llama-3.3-70b-versatile` | 2,000 | Backup 1 |
| 3 | 🔵 **Gemini 1** | `gemini-2.0-flash-exp` | 8,000 | Flash rápido |
| 4 | 🟢 **Groq 3** | `llama-3.1-8b-instant` | 2,000 | Rápido/ligero |
| 5 | 🟠 **DeepSeek 1** | `deepseek-chat` | 4,000 | Chat principal |
| 6 | 🔵 **Gemini 2** | `gemini-2.0-flash-exp` | 8,000 | Flash backup |
| 7 | 🟠 **DeepSeek 2** | `deepseek-chat` | 4,000 | Chat backup |
| 8 | 🔴 **OpenRouter** | `llama-3.1-8b-instruct:free` | 2,000 | Último recurso |

### ¿Cómo funciona?

1. Intenta la API #1 (Groq Principal)
2. Si falla (rate limit 429, timeout, error), salta automáticamente a la #2
3. Continúa en cascada hasta que una API responda exitosamente
4. Mantiene la última API exitosa como actual para la siguiente consulta
5. Notifica al usuario cuando cambia de API

## Funcionalidades de Notion

El bot tiene acceso directo a Notion mediante function calling:

- **`notion_search(query)`** — Busca páginas en el workspace
- **`notion_fetch(page_id)`** — Lee contenido completo de una página
- **`notion_create(parent_id, title, content)`** — Crea nuevas páginas

## Documentación interactiva

FastAPI genera documentación automática:

- **Swagger UI:** http://localhost:8001/docs
- **ReDoc:** http://localhost:8001/redoc

## Archivos del proyecto

```
NexusAgentes/
├── nexus_bot.py              # Bot principal v2.0 (FastAPI + fallback multi-API)
├── nexus_notion_tools.py     # Backend legacy (n8n)
├── requirements.txt          # Dependencias Python
├── .env                      # Configuración local (NO subir a git)
├── .env.example              # Template de configuración
├── test_basic.py             # Tests del backend legacy
├── test_ui.html              # Interfaz web de prueba
├── configure_n8n.py          # Script de configuración n8n
├── ESTADO_NEXUSAGENTES.md    # Reporte de estado del proyecto
└── README.md                 # Este archivo
```

## Troubleshooting

### Error: "Todas las APIs fallaron"

1. Verifica que al menos una API key esté configurada en `.env`
2. Revisa los logs del servidor para ver qué API específica falló
3. Espera unos minutos (posible rate limit) e intenta de nuevo

### Error: "TELEGRAM_BOT_TOKEN no está configurado"

1. Crea un bot con [@BotFather](https://t.me/botfather) en Telegram
2. Agrega `TELEGRAM_BOT_TOKEN` a tu `.env`

### Error: "NOTION_TOKEN no está configurado"

1. Crea una integración en [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Copia el token y agrégalo a tu `.env`
3. Comparte las páginas necesarias con la integración
