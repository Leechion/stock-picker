"""Trading API routes.

Endpoints:
  GET  /api/trading/account    - Account info (cash, total_value, pnl)
  GET  /api/trading/positions  - Current positions with live prices
  GET  /api/trading/logs       - Trade history (paginated)
  POST /api/trading/start      - Start trading bot
  POST /api/trading/stop       - Stop trading bot
  POST /api/trading/reset      - Reset account (clear all)
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.trading_service import (
    get_or_create_account,
    get_positions_with_prices,
    get_trade_logs,
    update_account_value,
    start_bot,
    stop_bot,
    reset_account,
)

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/trading/account")
async def get_account(session: AsyncSession = Depends(get_db)):
    account = await get_or_create_account(session)
    value_info = await update_account_value(session, account)
    await session.commit()
    return _ok({
        "id": account.id,
        "initial_capital": account.initial_capital,
        "cash": round(account.cash, 2),
        "total_value": round(account.total_value, 2),
        "is_active": account.is_active,
        **value_info,
    })


@router.get("/trading/positions")
async def get_positions(session: AsyncSession = Depends(get_db)):
    account = await get_or_create_account(session)
    records = await get_positions_with_prices(session, account.id)
    return _ok(records)


@router.get("/trading/logs")
async def list_trade_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    account = await get_or_create_account(session)
    records, total = await get_trade_logs(session, account.id, page, page_size)
    return _ok({
        "items": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    })


@router.post("/trading/start")
async def start_trading(session: AsyncSession = Depends(get_db)):
    result = await start_bot(session)
    return _ok(result)


@router.post("/trading/stop")
async def stop_trading(session: AsyncSession = Depends(get_db)):
    result = await stop_bot(session)
    return _ok(result)


@router.post("/trading/reset")
async def reset_trading(session: AsyncSession = Depends(get_db)):
    result = await reset_account(session)
    return _ok(result)
