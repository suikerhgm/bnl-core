from fastapi import APIRouter, HTTPException
from backend.utils import get_system_info, get_system_status, get_current_time, ping_host
from backend.models import SystemInfo, SystemStatus, PingResponse

router = APIRouter()

@router.get("/ping/{host}")
async def ping(host: str):
    if ping_host(host):
        return PingResponse(host=host, reachable=True)
    else:
        raise HTTPException(status_code=404, detail="Host no encontrado")

@router.get("/time")
async def get_time():
    return {"time": get_current_time()}

@router.get("/status")
async def get_status():
    return SystemStatus(**get_system_status())

@router.get("/system")
async def get_system():
    return SystemInfo(**get_system_info())