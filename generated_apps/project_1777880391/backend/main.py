from fastapi import FastAPI
from backend.routes import ping

app = FastAPI()

app.include_router(ping.router)