import datetime
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


@app.get("/time")
def time():
    return {"time": datetime.datetime.utcnow().isoformat() + "Z"}
