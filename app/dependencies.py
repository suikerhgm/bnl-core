"""
NexusAgentes — Dependencias compartidas de FastAPI (auth, etc.)
"""
from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.config import API_KEY

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(key: str = Security(_api_key_header)) -> None:
    """Verifica que la API key sea válida."""
    if key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key inválida",
        )
