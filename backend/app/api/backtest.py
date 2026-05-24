"""Backtest API routes."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.backtest import run_backtest

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.post("/backtest/run")
async def run_backtest_api(
    days: int = Query(default=180, ge=30, le=720, description="Backtest period in days"),
    top_n: int = Query(default=10, ge=1, le=50, description="Top N stocks to pick"),
    hold_days: int = Query(default=5, ge=1, le=20, description="Holding period in trading days"),
    session: AsyncSession = Depends(get_db),
):
    """Run a ranking-based backtest.

    Simulates picking the top N ranked stocks every ranking period,
    holding for hold_days, and calculating performance metrics.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        result = await run_backtest(session, start_date, end_date, top_n, hold_days)
        return _ok(result)
    except Exception as e:
        return _err(f"Backtest failed: {e}", 500)
