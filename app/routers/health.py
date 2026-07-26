from fastapi import APIRouter
from app.config import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "version": settings.APP_VERSION}
