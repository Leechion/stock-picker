from fastapi import APIRouter

from app.schemas.stock import HealthResponse

router = APIRouter()


@router.get("/health")
async def health_check():
    return HealthResponse(status="ok", version="0.1.0", database="sqlite+aiosqlite")
