from fastapi import APIRouter, Request
from app.services.telegram_service import handle_telegram_update

router = APIRouter()

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    await handle_telegram_update(data)
    return {"ok": True}
