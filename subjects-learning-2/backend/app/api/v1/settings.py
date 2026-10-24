from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/settings")
def get_public_settings():
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "ai_configured": bool(settings.deepseek_api_key),
        "model": settings.deepseek_model,
        "vision_model": settings.deepseek_vision_model,
    }
