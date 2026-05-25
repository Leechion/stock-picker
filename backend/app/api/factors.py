"""Factor API routes.

Endpoints:
  GET /api/factors/            - All factors for a stock (requires ?code=)
  GET /api/factors/groups      - Factor group definitions
  POST /api/factors/compute    - Compute factors for all stocks
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cache, cached
from app.models.stock import FactorType, FactorValue, StockInfo
from app.services.factor_engine import compute_all_factors
from app.services.factor_config import FACTOR_CONFIG

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/factors/")
@cached(ttl=300, prefix="factors")
async def get_factors_for_stock(
    code: str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    """Get raw factor values for a stock."""
    stmt = select(FactorValue).where(FactorValue.code == code)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return _ok([])
    data = [
        {
            "id": r.id,
            "code": r.code,
            "factor_name": r.factor_name,
            "factor_type": r.factor_type.value,
            "value": r.value,
            "computed_at": r.computed_at.isoformat() if r.computed_at else None,
        }
        for r in rows
    ]
    return _ok(data)


@router.get("/factors/group")
async def get_factors_grouped(
    code: str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    """Get factor values grouped by category."""
    stmt = select(FactorValue).where(FactorValue.code == code)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    groups = {"technical": [], "fundamental": [], "sentiment": []}
    for r in rows:
        factor_obj = {
            "id": r.id,
            "name": r.factor_name,
            "type": r.factor_type.value,
            "value": r.value,
            "computed_at": r.computed_at.isoformat() if r.computed_at else None,
        }
        cat = r.factor_type.value
        if cat in groups:
            groups[cat].append(factor_obj)
    return _ok(groups)


@router.get("/factors/groups")
async def get_factor_groups():
    """Get factor definitions with names, categories, and weights."""
    groups = []
    for category, factors in FACTOR_CONFIG.items():
        cat_factors = []
        for fname, fconfig in factors.items():
            if fname == "category_weight":
                continue
            cat_factors.append({"name": fname, "weight": fconfig.get("weight", 1.0)})
        groups.append({
            "name": category,
            "factors": cat_factors,
            "category_weight": factors.get("category_weight", 0),
        })
    return _ok(groups)


@router.post("/factors/compute")
async def compute_factors(
    session: AsyncSession = Depends(get_db),
):
    """Compute factors for all stocks (triggers factor recomputation + ranking)."""
    from datetime import date

    try:
        # Step 1: compute factors for all stocks
        from app.services.data_service import get_history

        result = await session.execute(select(StockInfo.code))
        codes = list(result.scalars().all())

        count = 0
        for code in codes:
            df = await get_history(session, code, days=80)
            if not df.empty:
                await compute_all_factors(session, code, df)
                count += 1

        # Step 2: compute rankings for ALL strategies
        from app.services.ranking_service import compute_all_rankings
        ranking_result = await compute_all_rankings(session, date.today())

        # Invalidate factor and ranking caches
        cache.invalidate("factors")
        cache.invalidate("ranking_")

        return _ok({
            "status": "success",
            "message": f"Computed factors for {count} stocks",
            "stocks_computed": count,
            "ranking": ranking_result,
        })
    except Exception as e:
        await session.rollback()
        return _err(f"Factor computation failed: {e}", 500)
