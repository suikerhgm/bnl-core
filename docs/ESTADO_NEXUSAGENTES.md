# 📊 Reporte de Estado — NexusAgentes

> **Fecha:** 25 de abril de 2026  
> **Versión del proyecto:** 2.0.1  
> **Propósito:** Agencia autónoma de desarrollo IA con integración Telegram → Python (FastAPI) → Notion + Sistema de Fallback Multi-API (8 APIs en cascada)

---

## 📦 Inventario de Archivos

| Archivo | Tamaño | Tipo | Propósito |
|---------|--------|------|-----------|
| `nexus_notion_tools.py` | 21,027 B | Python | Backend principal (FastAPI + lógica Notion) |
| `configure_n8n.py` | 6,848 B | Python | Script de configuración/importación de workflows en n8n |
| `test_basic.py` | 7,341 B | Python | Suite de pruebas del backend |
| `requirements.txt` | 97 B | Texto | Dependencias Python |
| `.env` | 179 B | Config | Variables de entorno (activo, con secretos) |
| `.env.example` | 131 B | Texto | Template de variables de entorno |
| `.gitignore` | 254 B | Texto | Exclusiones de Git |
| `README.md` | 5,087 B | Docs | Documentación del proyecto |
| `package.json` | 318 B | Node | Dependencias Node.js (WhatsApp Web) |
| `nexusagentes_workflow.json` | 7,430 B | JSON | Workflow n8n (versión original con API key hardcodeada) |
| `nexusagentes_configured.json` | 7,674 B | JSON | Workflow n8n (versión corregida con variable de entorno) |
| `workflow_backup.json` | 2,811 B | JSON | Workflow n8n (versión legacy con Gemini) |
| `test_ui.html` | 21,736 B | HTML | Interfaz web de prueba para los endpoints |
| `node_modules/` | -- | Carpeta | Dependencias Node.js instaladas |
| `__pycache__/` | -- | Carpeta | Caché de Python |
| `.claude/` | -- | Carpeta | Configuración de Claude |

### Archivos de configuración

| Archivo | Estado |
|---------|--------|
| `.env` | Presente y configurado (con NOTION_TOKEN, API_KEY, NOTION_VERSION, DEBUG) |
| `.env.example` | Template disponible |
| `.gitignore` | Configurado (excluye `.env`, `__pycache__/`, `node_modules/`, etc.) |
| `requirements.txt` | Dependencias Python definidas |
| `package.json` | Dependencias Node.js definidas |

---

## 🐍 Bot Principal (`nexus_bot.py`) -- v2.0.1

### Sistema de Fallback Multi-API (8 APIs en cascada)

| # | Proveedor | Modelo | Tokens | Proposito |
|---|-----------|--------|--------|-----------|
| 1 | **Groq 1** | `llama-3.3-70b-versatile` | 2,000 | Principal |
| 2 | **Groq 2** | `llama-3.3-70b-versatile` | 2,000 | Backup 1 |
| 3 | **Gemini 1** | `gemini-1.5-flash` | 8,000 | Flash rapido |
| 4 | **Groq 3** | `llama-3.1-8b-instant` | 2,000 | Rapido/ligero |
| 5 | **DeepSeek 1** | `deepseek-chat` | 4,000 | Chat principal |
| 6 | **Gemini 2** | `gemini-1.5-flash` | 8,000 | Flash backup |
| 7 | **DeepSeek 2** | `deepseek-chat` | 4,000 | Chat backup |
| 8 | **OpenRouter** | `llama-3.1-8b-instruct:free` | 2,000 | Ultimo recurso |

**Cambios en v2.0.1 (bugfixes):**
- **Fix Gemini**: Modelo corregido de `gemini-2.0-flash-exp` (404) a `gemini-1.5-flash` (valido en REST API v1beta)
- **Fix DeepSeek/OpenRouter**: Ahora usan `AttrDict` para convertir respuestas dict a objetos con acceso por atributos (`.content`, `.tool_calls`, etc.)
- **Nueva clase `AttrDict`**: Convierte diccionarios anidados en objetos con acceso por atributos, permitiendo que DeepSeek, OpenRouter y Gemini devuelvan respuestas compatibles con el mismo codigo que usa Groq

**Mecanismo de fallback:**
- Intenta APIs en orden de prioridad
- Si una falla (rate limit 429, timeout, error), salta a la siguiente automaticamente
- Mantiene estado global de que API esta usando actualmente
- Notifica al usuario cuando cambia de API

### Endpoints REST

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| `GET` | `/` | Health check + estado del bot |
| `POST` | `/webhook` | Webhook de Telegram (recibe mensajes) |
| `POST` | `/set-webhook` | Configura URL del webhook |
| `GET` | `/webhook-info` | Info del webhook actual |
| `GET` | `/api-status` | Estado detallado de todas las APIs |

### Funciones de Notion (integradas)

| Funcion | Descripcion |
|---------|-------------|
| `notion_search(query)` | Busca paginas en Notion |
| `notion_fetch(page_id)` | Lee contenido completo de una pagina |
| `notion_create(parent_id, title, content)` | Crea nueva pagina |

### Dependencias (`requirements.txt`)

| Paquete | Version | Proposito |
|---------|---------|-----------|
| `fastapi` | 0.109.0 | Framework web REST |
| `uvicorn` | 0.27.0 | Servidor ASGI |
| `python-dotenv` | 1.0.0 | Carga de variables de entorno |
| `httpx` | 0.28.1 | Cliente HTTP async |
| `groq` | 1.2.0 | SDK oficial de Groq (AsyncGroq) |

### Entry point

```bash
uvicorn nexus_bot:app --host 0.0.0.0 --port 8001
```

---

## 🔌 Integraciones

### Telegram

| Aspecto | Estado |
|---------|--------|
| Bot Token | Configurado en `.env` (`TELEGRAM_BOT_TOKEN`) |
| Webhook | Endpoint `/webhook` en FastAPI (puerto 8001) |
| Mensajes | Procesamiento directo sin n8n |

### Sistema Multi-API (8 APIs en cascada)

| Aspecto | Estado |
|---------|--------|
| Groq (3 keys) | Configuradas (`GROQ_API_KEY_1`, `_2`, `_3`) |
| Gemini (2 keys) | Configuradas (`GEMINI_API_KEY_1`, `_2`) |
| DeepSeek (2 keys) | Configuradas (`DEEPSEEK_API_KEY_1`, `_2`) |
| OpenRouter (1 key) | Configurado (`OPENROUTER_API_KEY`) |
| Fallback automatico | Implementado en `call_ai_with_fallback()` |
| Notificacion al usuario | Cuando cambia de API |

### Notion

| Aspecto | Estado |
|---------|--------|
| Token | Configurado en `.env` (`NOTION_TOKEN=ntn_...`) |
| Version API | `2022-06-28` |
| Timeout | 30 segundos |
| Funciones | `search`, `fetch`, `create` via REST directo |

### Gemini (Legacy)

| Aspecto | Estado |
|---------|--------|
| Estado | Deprecado -- solo existe en `workflow_backup.json` |
| API Key | Hardcodeada en el JSON |
| Modelo | `gemini-1.5-flash` |

---

## ⚙️ Configuracion Actual

### Variables de entorno (`.env`)

```env
NOTION_TOKEN=***REMOVED***
NOTION_VERSION=2022-06-28
API_KEY=***REMOVED***
DEBUG=false
```

### Workflows n8n

#### 1. `nexusagentes_workflow.json` -- Version Original
- **Nombre:** Nexus BNL -- Telegram + Groq + Notion Tools
- **Estado:** `active: false`
- **Problema:** API Key hardcodeada en los headers de los 3 nodos HTTP

#### 2. `nexusagentes_configured.json` -- Version Corregida
- **Nombre:** Nexus BNL -- Telegram + Groq + Notion Tools
- **Estado:** `active: false`
- **Mejora:** API Key ahora usa `{{ $env.NEXUS_API_KEY }}` (variable de entorno)

#### 3. `workflow_backup.json` -- Version Legacy (Gemini)
- **Nombre:** NexusAgentes -- Telegram + Gemini
- **Estado:** `active: false`
- **Problema:** API Key de Gemini hardcodeada

---

## ✅ Siguiente Paso Recomendado

### Inmediatos (orden sugerido)

1. **Iniciar Nexus BNL Bot v2.0.1**
   - Ejecutar: `uvicorn nexus_bot:app --host 0.0.0.0 --port 8001`
   - Verificar health: `curl http://localhost:8001/`
   - Verificar APIs: `curl http://localhost:8001/api-status`
   - Configurar webhook con ngrok + `set-webhook`

2. **Probar el bot en Telegram**
   - Enviar mensaje a @nexusagentes_bot
   - Verificar que responde correctamente (sin errores de atributo dict)
   - Probar busqueda, fetch y creacion de paginas en Notion

### A mediano plazo

3. **Limpiar archivos legacy**
   - Eliminar `workflow_backup.json` (contiene API key hardcodeada)

4. **Mejorar seguridad**
   - Agregar autenticacion opcional al endpoint `/health`
   - Considerar mover las API keys a un gestor de secretos

---

*Reporte generado automaticamente el 25 de abril de 2026*
