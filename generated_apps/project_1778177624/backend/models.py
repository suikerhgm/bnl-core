from pydantic import BaseModel

class PingResponse(BaseModel):
    """Respuesta del endpoint de ping"""
    message: str

class TimeResponse(BaseModel):
    """Respuesta del endpoint de tiempo"""
    time: str

class StatusResponse(BaseModel):
    """Respuesta del endpoint de estado"""
    status: str