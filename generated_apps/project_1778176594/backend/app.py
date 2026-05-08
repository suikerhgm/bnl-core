from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from backend import ping, time, status

app = FastAPI()

@app.get("/ping")
async def read_ping():
    return ping.ping()

@app.get("/time")
async def read_time():
    return time.time()

@app.get("/status")
async def read_status():
    return status.status()

@app.get("/healthcheck")
async def healthcheck():
    try:
        ping.ping()
        time.time()
        status.status()
        return JSONResponse(content={"message": "Sistema operativo"}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"message": str(e)}, status_code=500)