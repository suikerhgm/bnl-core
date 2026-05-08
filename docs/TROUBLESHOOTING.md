# 🔧 Troubleshooting — Nexus BNL

Guía de solución de problemas comunes al configurar y ejecutar Nexus BNL.

---

## 1. "400 The connection timed out"

**Error en n8n:** Al ejecutar el workflow, los nodos HTTP (`notion_search`, `notion_fetch`, `notion_create`) fallan con timeout.

### Causas posibles

- El backend Python no está corriendo
- El backend está en un puerto diferente
- Firewall bloqueando la conexión local

### Solución

```bash
# 1. Verificar que el backend esté corriendo
curl http://localhost:8000/health

# 2. Si no responde, iniciar el backend
cd C:\Users\lenovo\NexusAgentes
uvicorn nexus_notion_tools:app --host 127.0.0.1 --port 8000 --reload

# 3. Verificar que el puerto sea correcto
#    El workflow usa http://localhost:8000/search, /fetch, /create
#    Si cambiaste el puerto, actualiza las URLs en los nodos HTTP
```

### Si el backend está corriendo pero aún hay timeout

1. Abre el nodo HTTP problemático en n8n
2. Ve a **Options** → **Timeout**
3. Aumenta el valor a `120000` (120 segundos) — ya configurado en v2
4. Guarda y prueba de nuevo

---

## 2. "404 Could not load the workflow"

**Error en n8n:** Al importar el archivo JSON del workflow.

### Causas posibles

- El archivo JSON tiene errores de sintaxis
- El archivo contiene referencias a nodos o IDs que no existen
- Versión incorrecta de n8n

### Solución

```bash
# 1. Validar que el JSON sea sintácticamente correcto
python -c "import json; json.load(open('nexus_bnl_workflow_v2.json')); print('✅ JSON válido')"

# 2. Verificar la versión de n8n
#    El workflow requiere n8n v1.0+ con los siguientes paquetes:
#    - @n8n/n8n-nodes-langchain (para AI Agent y Groq)
#    - n8n-nodes-base (para Telegram y HTTP Request)
```

### Importación manual correcta

1. Abre n8n en tu navegador (`http://localhost:5678`)
2. Ve a **Workflows** en el panel izquierdo
3. Haz clic en **Add Workflow** → **Import from File**
4. Selecciona `nexus_bnl_workflow_v2.json`
5. Si ves errores de nodos faltantes, instala los paquetes necesarios:
   - Settings → Community Nodes → Instalar `@n8n/n8n-nodes-langchain`

---

## 3. "User attempted to access a workflow without permissions"

**Error en n8n:** Al intentar activar o ejecutar el workflow.

### Causas posibles

- El usuario no tiene permisos de owner/admin
- La instancia de n8n tiene autenticación multi-usuario
- El workflow fue importado por otro usuario

### Solución

1. Verifica tu rol en n8n:
   - Ve a **Settings** → **Users**
   - Asegúrate de ser **Owner** o **Admin**

2. Si es una instancia compartida:
   - El workflow debe ser importado por un owner
   - O el owner debe compartir el workflow contigo

3. Si es tu instancia local:
   - Asegúrate de haber iniciado sesión con el usuario owner
   - Por defecto, el primer usuario en registrarse es owner

---

## 4. "Backend Python no responde"

**Síntoma:** `curl http://localhost:8000/health` no responde o da error de conexión.

### Solución paso a paso

```bash
# 1. Verificar que Python esté instalado
python --version

# 2. Verificar que las dependencias estén instaladas
pip list | findstr fastapi
pip list | findstr uvicorn
pip list | findstr notion-client

# 3. Si faltan dependencias, instalarlas
pip install -r requirements.txt

# 4. Verificar que el archivo .env exista y tenga las variables necesarias
type .env
# Debe contener: NOTION_TOKEN, API_KEY, NOTION_VERSION

# 5. Iniciar el servidor manualmente
cd C:\Users\lenovo\NexusAgentes
uvicorn nexus_notion_tools:app --host 127.0.0.1 --port 8000 --reload

# 6. En otra terminal, probar el health check
curl http://localhost:8000/health
# Respuesta esperada: {"status":"ok","notion_connected":true}
```

### Errores comunes al iniciar

| Error | Causa | Solución |
|-------|-------|----------|
| `ValueError: NOTION_TOKEN no encontrado` | Falta `.env` o variable | Crear `.env` desde `.env.example` |
| `ModuleNotFoundError: No module named 'fastapi'` | Dependencias no instaladas | `pip install -r requirements.txt` |
| `Error: [Errno 10013]` | Puerto 8000 en uso | Cerrar el proceso que lo ocupa o cambiar puerto |
| `Error: [Errno 10048]` | Puerto ocupado por otro servicio | `netstat -ano \| findstr :8000` y matar proceso |

---

## 5. "Bot de Telegram no responde"

**Síntoma:** Envías un mensaje al bot pero no obtienes respuesta.

### Solución paso a paso

```bash
# 1. Verificar que el bot token sea válido
curl https://api.telegram.org/bot[TU_TOKEN]/getMe
# Si responde con {"ok":true,"result":{"id":...,"first_name":"...","username":"..."}} → token válido
# Si responde {"ok":false,"error_code":401} → token inválido

# 2. Verificar que el workflow esté ACTIVO en n8n
#    El interruptor debe estar en verde (Active)

# 3. Verificar que el webhook esté configurado
#    En n8n, abre el nodo Telegram Trigger
#    Debe mostrar "Webhook URL: https://.../webhook/..."
#    Si no aparece, guarda el nodo y recarga

# 4. Verificar que el backend Python esté corriendo
curl http://localhost:8000/health

# 5. Probar el flujo completo manualmente
#    - Envía un mensaje al bot
#    - En n8n, ve a Executions → ver si hay ejecuciones
#    - Si hay errores, haz clic en la ejecución para ver el detalle
```

### Checklist rápido

- [ ] ¿El bot token es correcto? (pruébalo con `getMe`)
- [ ] ¿El workflow está **Active** en n8n?
- [ ] ¿El backend Python está corriendo en `localhost:8000`?
- [ ] ¿Las credenciales de Telegram están configuradas en n8n?
- [ ] ¿La variable `NEXUS_API_KEY` está definida en n8n?
- [ ] ¿El bot fue iniciado? (envía `/start` al bot)

### Si el webhook no se registra

```bash
# Forzar registro manual del webhook
# Reemplaza [TOKEN] y [WEBHOOK_URL]
curl -X POST "https://api.telegram.org/bot[TOKEN]/setWebhook?url=[WEBHOOK_URL]"
```

---

## 6. "Groq API Key inválida"

**Error en n8n:** El nodo Groq Chat Model muestra error de autenticación.

### Solución

1. Verifica tu API Key en [console.groq.com](https://console.groq.com)
2. Asegúrate de que la key no haya expirado
3. En n8n, ve a **Credentials** → edita la credencial de Groq
4. Pega la key nuevamente (sin espacios extras)
5. Guarda y prueba

### Límites de Groq (free tier)

- **Requests por minuto:** 30 RPM (en modelos populares)
- **Tokens por minuto:** 15,000 TPM
- **Tokens por día:** 1,000,000 TPD

Si excedes estos límites, espera unos minutos y reintenta.

---

## 7. "Notion API Error: 401 Unauthorized"

**Error en el backend:** Al hacer `/search`, `/fetch` o `/create`.

### Solución

1. Verifica que `NOTION_TOKEN` en `.env` sea correcto
2. Asegúrate de que la integración de Notion tenga acceso a las páginas:
   - Abre la página en Notion
   - Haz clic en **...** (menú de página) → **Add connections**
   - Busca y selecciona tu integración (ej: "NexusAgentes")
3. Verifica que el token no haya expirado (los tokens de integración no expiran, pero pueden ser revocados)
4. Reinicia el backend después de cualquier cambio en `.env`

---

## 8. "El workflow se ejecuta pero no usa las herramientas de Notion"

**Síntoma:** El AI Agent responde pero no llama a `notion_search`, `notion_fetch` o `notion_create`.

### Solución

1. Verifica las conexiones en el workflow:
   - Los nodos `notion_search`, `notion_fetch`, `notion_create` deben estar conectados al AI Agent como **ai_tools** (no como main)
   - La conexión correcta se ve así en el JSON:
     ```json
     "notion_search": {
       "ai_tools": [
         [{ "node": "AI Agent", "type": "ai_tools", "index": 0 }]
       ]
     }
     ```

2. Verifica el system prompt:
   - El AI Agent debe tener las herramientas descritas en su system prompt
   - Si el prompt no menciona las herramientas, el agente no sabrá que existen

3. Prueba con un mensaje explícito:
   - Envía: "Busca 'ÉLITE' en Notion usando notion_search"
   - Si responde correctamente, el problema es que el prompt no es lo suficientemente claro

---

## 9. "Error: No module named 'dotenv'"

**Error al iniciar el backend Python.**

### Solución

```bash
# Instalar todas las dependencias
pip install -r requirements.txt

# O instalar específicamente
pip install python-dotenv
```

---

## 10. "El workflow no aparece después de importarlo"

**Síntoma:** Importaste el JSON pero no ves el workflow en ningún lado.

### Solución

1. Recarga la página de n8n (F5)
2. Ve a **Workflows** → busca por "Nexus BNL"
3. Si no aparece, intenta la importación manual:
   - Workflows → Add Workflow → Import from File
   - Selecciona `nexus_bnl_workflow_v2.json`
4. Si sigue sin aparecer, verifica los logs de n8n:
   ```bash
   # Si usas Docker
   docker logs n8n-instance-name
   ```

---

## Referencia rápida de puertos y URLs

| Servicio | URL | Puerto |
|----------|-----|--------|
| Backend Python | `http://localhost:8000` | 8000 |
| n8n Web UI | `http://localhost:5678` | 5678 |
| n8n API | `http://localhost:5678/api/v1` | 5678 |
| Telegram API | `https://api.telegram.org/bot[TOKEN]/` | 443 |
| Groq API | `https://api.groq.com/openai/v1` | 443 |
| Notion API | `https://api.notion.com/v1` | 443 |

---

*Documentación de troubleshooting — Nexus BNL v2*
