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
    get_account,
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
async def get_account_endpoint(session: AsyncSession = Depends(get_db)):
    account = await get_account(session)
    if account is None:
        return _ok({
            "id": None,
            "initial_capital": 500000.0,
            "cash": 500000.0,
            "total_value": 500000.0,
            "is_active": False,
            "position_value": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_pct": 0.0,
        })
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
    account = await get_account(session)
    if account is None:
        return _ok([])
    records = await get_positions_with_prices(session, account.id)
    return _ok(records)


@router.get("/trading/logs")
async def list_trade_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    account = await get_account(session)
    if account is None:
        return _ok({"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0})
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

    account = await get_account(session)
    if account is None:
        return _err("无交易账户")
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


@router.post("/trading/manual-buy")
async def manual_buy(
    code: str = Query(..., description="股票代码"),
    price: float | None = Query(default=None, description="买入价格，不填则取实时行情"),
    session: AsyncSession = Depends(get_db),
):
    """Manually buy a stock by code."""
    import asyncio
    from app.services.trading_service import (
        get_or_create_account,
        execute_buy,
        compute_atr,
        refresh_live_prices,
    )
    from app.models.stock import StockInfo
    from sqlalchemy import select

    account = await get_or_create_account(session)
    if not account.is_active:
        return _err("交易未启动，请先点击'启动交易'")

    # Check if already holding
    from app.models.trading import Position
    stmt = select(Position).where(Position.account_id == account.id, Position.code == code)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        return _err(f"已持有 {code}，不能重复买入")

    # Get stock name
    name_stmt = select(StockInfo.name).where(StockInfo.code == code)
    nr = await session.execute(name_stmt)
    name = nr.scalar_one_or_none() or code

    # Get price
    if price is None:
        loop = asyncio.get_running_loop()
        prices = await loop.run_in_executor(None, refresh_live_prices, [code])
        price = prices.get(code)
        if not price:
            return _err(f"无法获取 {code} 的实时价格，请手动输入价格")

    # Compute ATR for stop-loss
    atr = await compute_atr(session, code)
    if atr is None:
        atr = round(price * 0.05, 2)  # fallback: 5% of price

    # Use a high rank (1) for manual buys to maximize position size
    log = await execute_buy(session, account, code, name, rank=1, price=price, atr=atr)
    if log is None:
        return _err(f"资金不足，无法买入 {name}({code}) @ {price:.2f}")

    await session.commit()
    return _ok({
        "code": code,
        "name": name,
        "shares": log.shares,
        "price": log.price,
        "amount": round(log.amount, 2),
        "stop_loss": round(price - 2 * atr, 2),
        "reason": log.reason,
    })
