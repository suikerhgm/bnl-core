from fastapi import APIRouter, Response

router = APIRouter()

@router.get("/ping")
def read_ping():
    return {"ping": "pong"}