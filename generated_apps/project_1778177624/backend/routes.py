from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from backend.utils import ping, get_time, get_status
from backend.models import PingResponse, TimeResponse, StatusResponse

router = APIRouter()

@router.get("/ping")
async def ping_endpoint():
    """Endpoint para realizar un ping al servidor"""
    response = ping()
    return JSONResponse(content=response, media_type="application/json")

@router.get("/time")
async def time_endpoint():
    """Endpoint para obtener la hora actual del servidor"""
    response = get_time()
    return JSONResponse(content=response, media_type="application/json")

@router.get("/status")
async def status_endpoint():
    """Endpoint para obtener el estado del servidor"""
    response = get_status()
    return JSONResponse(content=response, media_type="application/json")