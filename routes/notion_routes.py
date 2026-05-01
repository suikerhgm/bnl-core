"""
NexusAgentes — Rutas de Notion (search, fetch, create, health)
"""
from fastapi import APIRouter, Depends, HTTPException
from notion_client import APIResponseError

from app.config import notion_client, logger
from app.dependencies import verify_api_key
from models.schemas import SearchRequest, FetchRequest, CreateRequest
from services.notion_service import notion_search, notion_fetch, notion_create

router = APIRouter(tags=["Notion"])


@router.get("/health")
async def health_check():
    """Health check del servicio. Verifica conexion con Notion."""
    logger.info("Health check solicitado")
    notion_connected = False

    try:
        notion_client.users.me()
        notion_connected = True
    except APIResponseError:
        logger.warning("Health check: No se pudo conectar con Notion API")
    except Exception as e:
        logger.error(f"Health check error: {e}")

    return {
        "status": "ok",
        "notion_connected": notion_connected,
    }


@router.post("/search", dependencies=[Depends(verify_api_key)])
async def search_notion(request: SearchRequest):
    """Buscar paginas en Notion por termino de busqueda."""
    logger.info(f"POST /search | query='{request.query}'")

    try:
        results = notion_search(request.query)
        logger.info(f"POST /search | 200 OK | {len(results)} resultados")
        return {"status": "success", "data": results}
    except APIResponseError as e:
        logger.error(f"POST /search | 502 | Notion API error: {e}")
        raise HTTPException(
            status_code=502, detail=f"Notion API error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"POST /search | 500 | Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/fetch", dependencies=[Depends(verify_api_key)])
async def fetch_notion(request: FetchRequest):
    """Leer contenido completo de una pagina de Notion."""
    logger.info(f"POST /fetch | page_id='{request.page_id}'")

    try:
        result = notion_fetch(request.page_id)
        logger.info(
            f"POST /fetch | 200 OK | title='{result['title']}' | "
            f"{len(result['content'])} chars"
        )
        return {"status": "success", "data": result}
    except APIResponseError as e:
        logger.error(f"POST /fetch | 502 | Notion API error: {e}")
        raise HTTPException(
            status_code=502, detail=f"Notion API error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"POST /fetch | 500 | Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/create", dependencies=[Depends(verify_api_key)])
async def create_notion(request: CreateRequest):
    """Crear una nueva pagina en Notion."""
    logger.info(
        f"POST /create | title='{request.title}' | "
        f"parent='{request.parent_id}' | content_len={len(request.content)}"
    )

    try:
        result = notion_create(
            parent_id=request.parent_id,
            title=request.title,
            content=request.content,
        )
        logger.info(
            f"POST /create | 200 OK | id='{result['id']}' | "
            f"url='{result['url']}'"
        )
        return {"status": "success", "data": result}
    except APIResponseError as e:
        logger.error(f"POST /create | 502 | Notion API error: {e}")
        raise HTTPException(
            status_code=502, detail=f"Notion API error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"POST /create | 500 | Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
