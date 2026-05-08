from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from api import ping, time, status

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(ping.router)
app.include_router(time.router)
app.include_router(status.router)

@app.get("/")
def read_root():
    return HTMLResponse("""
    <html>
        <head>
            <title>App Web Status</title>
        </head>
        <body>
            <h1>App Web Status</h1>
            <a href="/ping">Ping</a>
            <a href="/time">Time</a>
            <a href="/status">Status</a>
            <script src="/static/script.js"></script>
        </body>
    </html>
    """)