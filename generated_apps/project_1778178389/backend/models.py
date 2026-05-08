from pydantic import BaseModel

class SystemInfo(BaseModel):
    system: str
    release: str
    version: str
    processor: str

class SystemStatus(BaseModel):
    cpu_percent: int
    memory_percent: int
    disk_percent: int

class PingResponse(BaseModel):
    host: str
    reachable: bool