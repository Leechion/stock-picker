"""Factor API routes.

Endpoints:
  GET /api/factors/            - All factors for a stock (requires ?code=)
  GET /api/factors/groups      - Factor group definitions
  POST /api/factors/compute    - Compute factors for all stocks
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cached
from app.models.stock import FactorType, FactorValue, StockInfo
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
    trading_date: date = Query(default=None),
    concurrency: int = Query(default=12, ge=1, le=32),
):
    """Launch the factor + ranking pipeline as a background job.

    This endpoint used to run the whole computation INLINE, one stock at a time:

        for code in codes:                       # ~3200 stocks, strictly serial
            df = await get_history(session, code, days=80)
            await compute_all_factors(session, code, df)

    That is the third divergent copy of this pipeline (the others being
    ``/rankings/compute`` and the scheduler). It was the slowest of the three —
    no concurrency whatsoever — and, like the others, blocked the HTTP request
    for its entire duration with no progress reporting.

    It now delegates to ``app.pipelines`` and returns a ``job_id`` immediately.
    """
    from app.core.jobs import launch

    target = trading_date or date.today()

    async def _run(ctx):
        from app.pipelines import run_full_ranking_pipeline

        return await run_full_ranking_pipeline(
            ctx, trading_date=target, concurrency=concurrency
        )

    job_id = await launch(
        "full_ranking",
        _run,
        {"trading_date": str(target), "concurrency": concurrency, "source": "factors"},
    )
    return _ok(
        {
            "job_id": job_id,
            "job_type": "full_ranking",
            "status": "pending",
            "trading_date": str(target),
            "poll_url": f"/api/jobs/{job_id}",
        },
        "任务已启动",
    )
