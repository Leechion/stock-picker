"""Strategy API routes - manage YAML-based factor strategies."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.strategy_loader import strategy_loader

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/strategies/")
async def list_strategies():
    """List all available strategies."""
    return _ok(strategy_loader.list_strategies())


@router.get("/strategies/active")
async def get_active_strategy():
    """Get the currently active strategy config."""
    config = strategy_loader.get_active_config()
    return _ok({
        "slug": strategy_loader.active_name,
        "config": config,
    })


@router.post("/strategies/{slug}/activate")
async def activate_strategy(slug: str):
    """Switch the active strategy by slug."""
    if strategy_loader.set_active(slug):
        return _ok({"slug": slug}, f"Strategy '{slug}' activated")
    return _err(f"Strategy '{slug}' not found", 404)


@router.post("/strategies/reload")
async def reload_strategies():
    """Re-scan the strategies directory for changes."""
    strategy_loader.reload()
    return _ok(strategy_loader.list_strategies(), "Strategies reloaded")
