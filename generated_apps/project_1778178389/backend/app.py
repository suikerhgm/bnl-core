from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from backend.routes import router
from backend.config import CONFIG

app = FastAPI(
    title="Sistema de Monitoreo",
    description="Aplicación web para monitorear el sistema",
    version="1.0.0",
)

app.include_router(router)

@app.get("/frontend")
async def get_frontend():
    with open("frontend.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content, media_type="text/html")

app.mount("/static", StaticFiles(directory="static"), name="static")