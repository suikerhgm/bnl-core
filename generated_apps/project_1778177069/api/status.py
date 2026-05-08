from fastapi import APIRouter

router = APIRouter()

@router.get("/status")
def read_status():
    return {"status": "ok"}