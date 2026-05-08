from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/time")
def read_time():
    return {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}