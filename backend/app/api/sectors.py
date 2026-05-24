"""Sector (industry) ranking API routes.

Endpoints:
  GET /api/sectors/              - List all sectors ranked by aggregate score
  GET /api/sectors/{industry}    - Get stocks within a specific sector
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cached

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/sectors/")
@cached(ttl=300, prefix="sector_rankings")
async def list_sector_rankings(
    trading_date: date = Query(default=None),
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    from app.services.ranking_service import get_sector_rankings

    target_date = trading_date or date.today()
    sectors = await get_sector_rankings(session, target_date, strategy=strategy)
    return _ok(sectors)


@router.get("/sectors/{industry}")
@cached(ttl=300, prefix="sector_stocks")
async def get_sector_detail(
    industry: str,
    trading_date: date = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    from app.services.ranking_service import get_sector_stocks

    target_date = trading_date or date.today()
    records, total = await get_sector_stocks(
        session, industry, target_date, page, page_size, strategy=strategy
    )
    return _ok({
        "industry": industry,
        "items": records,
        "total": total,
        "page": page,
        "page_size": page_size,
    })
