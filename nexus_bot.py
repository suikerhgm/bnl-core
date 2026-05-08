"""
🤖 NEXUS BNL — Servidor Web (FastAPI) para el Bot de Telegram
Capa de transporte únicamente; toda la lógica está en app/services/telegram_service.py

Stack:
- FastAPI (solo endpoints)
- Telegram webhook
- httpx

Autor: Claude + Leo
Versión: 3.0 (servicio separado, lógica en telegram_service.py)
"""
import asyncio
import os
import sys
import json
import logging
from datetime import datetime

# Ensure asyncio subprocesses work on Windows regardless of how uvicorn
# configures its event loop (especially under --reload worker processes).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv

# ── Importar lógica pura desde el servicio ─────────────────────
from app.services.telegram_service import (
    handle_telegram_update,
    API_CASCADE,
    current_api_index,
)

# ── Runtime Engine ──────────────────────────────────────────────
from core.runtime.runtime_engine import get_engine

# ── Auto-Loop Engine ─────────────────────────────────────────────
from core.auto_loop_engine import get_loop_engine

load_dotenv()

# Logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Nexus BNL Bot v3.0")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# ── Boot RuntimeEngine when the server starts ──────────────────
@app.on_event("startup")
async def _start_runtime_engine():
    get_engine().start()
    logger.info("🔄 RuntimeEngine started — watching generated_apps/")


# ===== TELEGRAM WEBHOOK =====

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Recibe updates de Telegram y delega en handle_telegram_update()"""
    try:
        body = await request.body()
        logger.info(f"📩 Update recibido: {len(body)} bytes")
        data = json.loads(body)
        await handle_telegram_update(data)
        return JSONResponse({"ok": True})

    except json.JSONDecodeError as e:
        logger.error(f"❌ Error decodificando JSON: {e}")
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    except Exception as e:
        logger.error(f"❌ Error en webhook: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ===== ENDPOINTS DE UTILIDAD =====

@app.get("/ping")
def ping():
    """Healthcheck para run.py y monitoreo externo."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Endpoint de salud"""
    return {
        "status": "✅ Nexus BNL Bot v3.0 activo",
        "timestamp": datetime.now().isoformat(),
        "bot": "@nexusagentes_bot",
        "apis_configured": sum(1 for c in API_CASCADE if c["api_key"]),
        "current_api": API_CASCADE[current_api_index]["name"]
    }


@app.post("/set-webhook")
async def set_webhook(request: Request):
    """Configura el webhook de Telegram con manejo robusto de errores"""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": "Body debe ser JSON válido"}
        )

    webhook_url = data.get("url")
    if not webhook_url:
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": "URL requerida en el body JSON"}
        )
    if not webhook_url.startswith("https://"):
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": "La URL debe comenzar con https://"}
        )

    cleaned_url = webhook_url.strip()
    while cleaned_url.startswith("https://https://"):
        cleaned_url = cleaned_url[len("https://"):]
        cleaned_url = "https://" + cleaned_url

    if cleaned_url != webhook_url:
        logger.warning(f"🔧 URL limpiada: {webhook_url} → {cleaned_url}")
        webhook_url = cleaned_url

    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {"url": webhook_url}
    logger.info(f"🔗 Configurando webhook: {webhook_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(telegram_api_url, json=payload, timeout=30.0)
            result = response.json()

            if response.status_code == 200 and result.get("ok"):
                logger.info(f"✅ Webhook configurado correctamente: {webhook_url}")
                return {"success": True, "result": result, "webhook_url": webhook_url}

            error_desc = result.get("description", "Error desconocido")
            logger.error(f"❌ Telegram rechazó webhook: {error_desc}")
            return JSONResponse(
                status_code=200,
                content={
                    "success": False,
                    "error": f"Telegram rechazó la petición: {error_desc}",
                    "telegram_response": result,
                    "webhook_url": webhook_url
                }
            )

    except httpx.HTTPStatusError as e:
        error_text = str(e)
        try:
            error_detail = e.response.json()
            error_text = error_detail.get("description", str(e))
        except Exception:
            pass
        logger.error(f"❌ Error HTTP al configurar webhook: {error_text}")
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": f"Error HTTP: {error_text}", "webhook_url": webhook_url}
        )

    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión al configurar webhook: {e}")
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": f"Error de conexión: {str(e)}", "webhook_url": webhook_url}
        )

    except Exception as e:
        logger.error(f"❌ Error inesperado en set_webhook: {e}", exc_info=True)
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": f"Error inesperado: {str(e)}"}
        )


@app.get("/webhook-info")
async def webhook_info():
    """Obtiene info del webhook actual"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            result = response.json()
            if response.status_code == 200 and result.get("ok"):
                info = result.get("result", {})
                logger.info(f"📡 Webhook info: {json.dumps(info, indent=2)}")
                return {"success": True, "result": info}
            error_desc = result.get("description", "Error desconocido")
            logger.error(f"❌ Error al obtener webhook info: {error_desc}")
            return JSONResponse(
                status_code=200,
                content={"success": False, "error": error_desc}
            )
    except httpx.RequestError as e:
        logger.error(f"❌ Error de conexión al obtener webhook info: {e}")
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": f"Error de conexión: {str(e)}"}
        )
    except Exception as e:
        logger.error(f"❌ Error inesperado en webhook-info: {e}", exc_info=True)
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": str(e)}
        )


@app.get("/api-status")
async def api_status():
    """Muestra estado de todas las APIs"""
    return {
        "current_index": current_api_index,
        "current_api": API_CASCADE[current_api_index]["name"],
        "cascade": [
            {
                "index": i,
                "name": config["name"],
                "model": config["model"],
                "configured": bool(config["api_key"])
            }
            for i, config in enumerate(API_CASCADE)
        ]
    }


@app.post("/build-app")
async def build_app(request: Request):
    """Genera un proyecto mínimo: backend FastAPI + index.html + README."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    idea = data.get("idea", "proyecto")
    import time
    from pathlib import Path

    project_id = f"app_{int(time.time())}"
    project_path = Path("generated_apps") / project_id
    project_path.mkdir(parents=True, exist_ok=True)

    # ── backend.py ───────────────────────────────────────────────
    backend_code = '''\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def index():
    return FileResponse("index.html")

@app.get("/ping")
def ping():
    return {"message": "pong"}
'''

    # ── index.html — fetch uses relative path, served via GET / ──
    html_code = f'''\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{idea}</title>
</head>
<body>
  <h1>{idea}</h1>
  <button onclick="pingBackend()">Ping backend</button>
  <p id="result"></p>
  <script>
    async function pingBackend() {{
      try {{
        const res = await fetch("/ping");
        const data = await res.json();
        document.getElementById("result").textContent = data.message;
      }} catch (e) {{
        document.getElementById("result").textContent = "Error: " + e;
      }}
    }}
  </script>
</body>
</html>
'''

    # ── README.txt ───────────────────────────────────────────────
    readme = f'''\
Proyecto: {idea}
Generado por Nexus BNL

Para correr:
    uvicorn backend:app --port 8002

Luego abre index.html en el navegador.
'''

    (project_path / "backend.py").write_text(backend_code, encoding="utf-8")
    (project_path / "index.html").write_text(html_code, encoding="utf-8")
    (project_path / "README.txt").write_text(readme, encoding="utf-8")

    files = ["backend.py", "index.html", "README.txt"]

    # ── Auto-launch backend via RuntimeEngine ─────────────────────
    launched = await get_engine().launch(project_id, project_path)
    logger.info(
        "🚀 /build-app: project '%s' created — launched=%s", project_id, launched
    )

    # ── Auto-loop: detect port and start correction cycle in background ──
    if launched:
        async def _run_autoloop():
            # AutoLoopEngine discovers the real port from RuntimeEngine internally —
            # no need to pre-read it here (avoids race where port isn't set yet).
            logger.info("🔁 /build-app: starting autoloop for '%s'", project_id)
            healthy = await get_loop_engine().run(project_id, project_path)
            logger.info("🔁 /build-app: autoloop finished for '%s' — healthy=%s",
                        project_id, healthy)

        asyncio.create_task(_run_autoloop())

    return JSONResponse({
        "success":      True,
        "message":      f"Proyecto '{idea}' creado en {project_path}",
        "project_path": str(project_path),
        "project_id":   project_id,
        "files":        files,
        "running":      launched,
    })


@app.get("/diagnose")
async def diagnose():
    """Endpoint de diagnóstico completo"""
    diagnostics = {
        "timestamp": datetime.now().isoformat(),
        "bot": "@nexusagentes_bot",
        "checks": {}
    }

    # 1. Verificar variables de entorno
    env_keys = [
        "TELEGRAM_BOT_TOKEN", "NOTION_TOKEN",
        "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3",
        "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
        "DEEPSEEK_API_KEY_1", "DEEPSEEK_API_KEY_2",
        "OPENROUTER_API_KEY"
    ]
    env_vars = {k: bool(os.getenv(k)) for k in env_keys}
    configured = sum(1 for v in env_vars.values() if v)
    diagnostics["checks"]["env_vars"] = {
        "configured": configured,
        "total": len(env_vars),
        "details": env_vars,
        "status": "✅ OK" if configured >= 2 else "❌ FALTAN VARIABLES CRÍTICAS"
    }

    # 2. Verificar conectividad con Telegram
    try:
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=15.0
            )
            me_result = me_resp.json()
            bot_username = me_result.get("result", {}).get("username", "unknown") if me_result.get("ok") else None
            diagnostics["checks"]["telegram_api"] = {
                "reachable": me_resp.status_code == 200 and me_result.get("ok"),
                "bot_username": bot_username,
                "status": "✅ OK" if me_result.get("ok") else f"❌ {me_result.get('description', 'Error')}"
            }

            wh_resp = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=15.0
            )
            wh_result = wh_resp.json()
            if wh_result.get("ok"):
                wh_info = wh_result.get("result", {})
                diagnostics["checks"]["webhook_info"] = {
                    "url": wh_info.get("url", "No configurado"),
                    "has_custom_certificate": wh_info.get("has_custom_certificate", False),
                    "pending_update_count": wh_info.get("pending_update_count", 0),
                    "last_error_date": wh_info.get("last_error_date"),
                    "last_error_message": wh_info.get("last_error_message"),
                    "max_connections": wh_info.get("max_connections", 40),
                    "status": "✅ Webhook configurado" if wh_info.get("url") else "⚠️ Sin webhook configurado"
                }
            else:
                diagnostics["checks"]["webhook_info"] = {
                    "error": wh_result.get("description", "Error desconocido"),
                    "status": "❌ Error"
                }
    except httpx.RequestError as e:
        diagnostics["checks"]["telegram_api"] = {
            "reachable": False, "error": str(e), "status": "❌ No se puede conectar con Telegram"
        }

    # 3. Servidor local
    diagnostics["checks"]["server"] = {
        "host": "0.0.0.0", "port": 8001, "status": "✅ Servidor activo"
    }

    # 4. APIs de IA
    cascade_status = [
        {
            "index": i,
            "name": c["name"],
            "model": c["model"],
            "configured": bool(c["api_key"]),
            "status": "✅ Configurada" if bool(c["api_key"]) else "⚠️ Sin API key"
        }
        for i, c in enumerate(API_CASCADE)
    ]
    diagnostics["checks"]["ai_cascade"] = {
        "total": len(API_CASCADE),
        "configured": sum(1 for c in API_CASCADE if c["api_key"]),
        "current_api": API_CASCADE[current_api_index]["name"],
        "cascade": cascade_status
    }

    # 5. Endpoints
    diagnostics["endpoints"] = {
        "/": "GET - Health check",
        "/webhook": "POST - Telegram updates",
        "/set-webhook": "POST - Configurar webhook",
        "/webhook-info": "GET - Información del webhook",
        "/api-status": "GET - Estado de APIs de IA",
        "/diagnose": "GET - Este diagnóstico"
    }

    diagnostics["overall_status"] = "✅ Todo OK" if all(
        str(check.get("status", "") or "").startswith("✅")
        for check in diagnostics["checks"].values()
        if isinstance(check, dict)
    ) else "⚠️ Hay problemas que revisar"

    return diagnostics


# ── ERROR_TAXONOMY_SYSTEM: /repair/status endpoint ──────────────────────────

@app.get("/repair/status")
async def repair_status():
    """Return repair metrics and recent history from ERROR_TAXONOMY_SYSTEM."""
    try:
        from core.repair.repair_tracker import get_metrics, get_history
        from core.repair_engine import get_repair_engine
        metrics = get_metrics()
        history = get_history(limit=30)
        active  = list(get_repair_engine()._active)
        return {
            "metrics": metrics,
            "active_repairs": active,
            "history": history,
        }
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/repair/dashboard", response_class=HTMLResponse)
async def repair_dashboard():
    """Serve the repair dashboard HTML."""
    from pathlib import Path as _P
    dash = _P("app/repair_dashboard.html")
    if dash.exists():
        return HTMLResponse(content=dash.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>repair_dashboard.html not found</h1>", status_code=404)


# ── VM Isolation Routes ──────────────────────────────────────────
from app.routes.vm_routes import router as vm_router
app.include_router(vm_router)


if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando Nexus BNL Bot v3.0...")
    print(f"📊 APIs configuradas: {sum(1 for c in API_CASCADE if c['api_key'])}/8")
    print(f"🎯 API principal: {API_CASCADE[0]['name']}")
    print(f"🧠 Lógica en: app/services/telegram_service.py")
    uvicorn.run(app, host="0.0.0.0", port=8001)
