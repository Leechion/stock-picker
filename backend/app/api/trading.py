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


@router.post("/trading/run-now")
async def run_trading_now(session: AsyncSession = Depends(get_db)):
    """Manually trigger pre-market check (buy/sell)."""
    from app.services.trading_service import pre_market_check
    actions = await pre_market_check(session)
    return _ok({"actions": actions, "count": len(actions)})


@router.post("/trading/daily-summary")
async def daily_summary(session: AsyncSession = Depends(get_db)):
    """Calculate daily P&L with real closing prices and send to WeChat."""
    import asyncio
    from app.services.trading_service import refresh_live_prices

    account = await get_or_create_account(session)
    from app.models.trading import Position
    from sqlalchemy import select
    stmt = select(Position).where(Position.account_id == account.id)
    result = await session.execute(stmt)
    positions = result.scalars().all()

    if not positions:
        return _err("无持仓数据")

    # Fetch real closing prices
    codes = [p.code for p in positions]
    loop = asyncio.get_running_loop()
    close_prices = await loop.run_in_executor(None, refresh_live_prices, codes)

    # Calculate P&L
    lines = [
        "## 📊 模拟交易日报",
        "",
        "| 股票 | 买入价 | 收盘价 | 盈亏 | 盈亏率 |",
        "|------|--------|--------|------|--------|",
    ]

    total_pnl = 0
    for p in positions:
        close = close_prices.get(p.code)
        if not close:
            continue
        pnl = (close - p.avg_cost) * p.shares
        pnl_pct = (close - p.avg_cost) / p.avg_cost * 100
        total_pnl += pnl
        sign = "+" if pnl >= 0 else ""
        lines.append(f"| {p.name} | {p.avg_cost:.2f} | {close:.2f} | {sign}{pnl:.0f} | {sign}{pnl_pct:.2f}% |")

    position_value = sum(
        close_prices.get(p.code, p.avg_cost) * p.shares for p in positions
    )
    total_value = account.cash + position_value
    total_pnl_pct = total_pnl / account.initial_capital * 100
    arrow = "🔴" if total_pnl < 0 else "🟢"

    lines.extend([
        "",
        f"{arrow} **总资产** ¥{total_value:,.2f}",
        f"- 可用资金 ¥{account.cash:,.2f}",
        f"- 持仓市值 ¥{position_value:,.2f}",
        f"- 今日盈亏 ¥{total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)",
    ])

    msg = "\n".join(lines)

    from app.services.notification_service import send_wechat_work
    from app.core.config import settings
    sent = send_wechat_work(settings.wechat_webhook_url, msg)

    return _ok({"sent": sent, "total_pnl": round(total_pnl, 2), "total_pnl_pct": round(total_pnl_pct, 2)})
