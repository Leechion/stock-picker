"""Trading service - simulated trading engine with pyramid sizing, ATR stop-loss, mixed take-profit."""

from __future__ import annotations

import time
from datetime import date, datetime

from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockDaily, StockInfo, StockRanking
from app.models.trading import Position, TradeLog, TradingAccount
from app.services.strategy_loader import strategy_loader


def _broadcast_trade_event(action: str, code: str, name: str, price: float, shares: int, pnl: float | None = None, reason: str = "") -> None:
    """Fire-and-forget broadcast of a trade event to WebSocket clients."""
    import asyncio
    from app.core.websocket import monitor_hub

    data = {
        "action": action,
        "code": code,
        "name": name,
        "price": price,
        "shares": shares,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(monitor_hub.broadcast("trades", data))
    except RuntimeError:
        pass


# ======================================================================
# Pyramid position sizing weights
# ======================================================================

def pyramid_weight(rank: int) -> float:
    """Return capital weight based on ranking position."""
    if rank <= 3:
        return 0.12
    elif rank <= 7:
        return 0.10
    else:
        return 0.08


# ======================================================================
# Account management
# ======================================================================

async def get_or_create_account(session: AsyncSession) -> TradingAccount:
    """Get the default trading account, creating one if needed."""
    result = await session.execute(select(TradingAccount).limit(1))
    account = result.scalar_one_or_none()
    if account is None:
        account = TradingAccount(initial_capital=500000.0, cash=500000.0, total_value=500000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)
    return account


# ======================================================================
# ATR computation
# ======================================================================

async def compute_atr(session: AsyncSession, code: str, period: int = 14) -> float | None:
    """Compute ATR (Average True Range) from recent daily data."""
    stmt = (
        select(StockDaily)
        .where(StockDaily.code == code)
        .order_by(StockDaily.trade_date.desc())
        .limit(period + 1)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    if len(rows) < period + 1:
        return None

    rows.reverse()  # oldest first

    true_ranges = []
    for i in range(1, len(rows)):
        high = rows[i].high
        low = rows[i].low
        prev_close = rows[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[-period:]) / period
    return round(atr, 4)


# ======================================================================
# Price fetching
# ======================================================================

async def get_latest_price(session: AsyncSession, code: str) -> float | None:
    """Get latest close price from stock_daily."""
    stmt = (
        select(StockDaily.close)
        .where(StockDaily.code == code)
        .order_by(StockDaily.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_high(session: AsyncSession, code: str) -> float | None:
    """Get latest high price."""
    stmt = (
        select(StockDaily.high)
        .where(StockDaily.code == code)
        .order_by(StockDaily.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ======================================================================
# Trade execution
# ======================================================================

async def execute_buy(
    session: AsyncSession,
    account: TradingAccount,
    code: str,
    name: str,
    rank: int,
    price: float,
    atr: float,
) -> TradeLog | None:
    """Execute a simulated buy order with pyramid sizing."""
    weight = pyramid_weight(rank)
    amount = account.initial_capital * weight
    shares = int(amount / price / 100) * 100  # A股整手

    if shares < 100:
        logger.warning(f"Not enough capital to buy {code}: need {amount:.0f}, shares={shares}")
        return None

    total_cost = shares * price
    if total_cost > account.cash:
        shares = int(account.cash / price / 100) * 100
        if shares < 100:
            logger.warning(f"Insufficient cash for {code}: cash={account.cash:.0f}")
            return None
        total_cost = shares * price

    stop_loss = round(price - 2 * atr, 2)

    position = Position(
        account_id=account.id,
        code=code,
        name=name,
        shares=shares,
        avg_cost=price,
        open_price=price,
        high_since_open=price,
        atr_at_buy=atr,
        stop_loss_price=stop_loss,
        tier=1,
    )
    session.add(position)

    account.cash -= total_cost

    log = TradeLog(
        account_id=account.id,
        code=code,
        name=name,
        action="buy",
        shares=shares,
        price=price,
        amount=total_cost,
        reason=f"排名#{rank} 金字塔建仓 ATR={atr:.2f} 止损={stop_loss:.2f}",
    )
    session.add(log)

    logger.info(f"BUY {name}({code}) {shares}股 @ {price:.2f} 止损={stop_loss:.2f}")
    _broadcast_trade_event("buy", code, name, price, shares, reason=log.reason)
    return log


async def execute_sell(
    session: AsyncSession,
    account: TradingAccount,
    position: Position,
    price: float,
    reason: str,
    action: str = "sell",
    shares: int | None = None,
) -> TradeLog:
    """Execute a simulated sell order (full or partial)."""
    sell_shares = shares or position.shares
    sell_shares = min(sell_shares, position.shares)

    amount = sell_shares * price
    pnl = (price - position.avg_cost) * sell_shares

    account.cash += amount

    if sell_shares >= position.shares:
        await session.delete(position)
    else:
        position.shares -= sell_shares

    log = TradeLog(
        account_id=account.id,
        code=position.code,
        name=position.name,
        action=action,
        shares=sell_shares,
        price=price,
        amount=amount,
        pnl=round(pnl, 2),
        reason=reason,
    )
    session.add(log)

    logger.info(f"SELL {position.name}({position.code}) {sell_shares}股 @ {price:.2f} 盈亏={pnl:.2f} 原因={reason}")
    _broadcast_trade_event(action, position.code, position.name, price, sell_shares, pnl=pnl, reason=reason)
    return log


# ======================================================================
# Add to position (pyramid layer 2/3)
# ======================================================================

async def check_and_execute_pyramid_add(
    session: AsyncSession,
    account: TradingAccount,
    position: Position,
    current_price: float,
) -> TradeLog | None:
    """Check if pyramid add conditions are met and execute."""
    if position.tier >= 3:
        return None

    gain_pct = (current_price - position.open_price) / position.open_price

    # Tier 2: +8%, Tier 3: +15%
    target_gain = 0.08 if position.tier == 1 else 0.15
    if gain_pct < target_gain:
        return None

    # Calculate add amount: 50% of original position value
    original_value = position.open_price * position.shares
    add_value = original_value * 0.5
    add_shares = int(add_value / current_price / 100) * 100

    if add_shares < 100 or add_shares * current_price > account.cash:
        return None

    total_cost = add_shares * current_price
    new_total_shares = position.shares + add_shares
    position.avg_cost = (position.avg_cost * position.shares + current_price * add_shares) / new_total_shares
    position.shares = new_total_shares
    position.tier += 1

    # Recalculate stop loss based on new avg cost
    atr = position.atr_at_buy
    position.stop_loss_price = round(position.avg_cost - 2 * atr, 2)

    account.cash -= total_cost

    log = TradeLog(
        account_id=account.id,
        code=position.code,
        name=position.name,
        action="buy",
        shares=add_shares,
        price=current_price,
        amount=total_cost,
        reason=f"金字塔加仓第{position.tier}层 盈利={gain_pct:.1%}",
    )
    session.add(log)

    logger.info(f"PYRAMID ADD {position.name} layer={position.tier} +{add_shares}股 @ {current_price:.2f}")
    return log


# ======================================================================
# Stop-loss & take-profit checks
# ======================================================================

async def check_stop_loss(
    session: AsyncSession,
    account: TradingAccount,
    position: Position,
    current_price: float,
) -> TradeLog | None:
    """Check ATR stop-loss. Sells entire position if triggered."""
    if current_price <= position.stop_loss_price:
        return await execute_sell(
            session, account, position, current_price,
            reason=f"ATR止损 触发价={position.stop_loss_price:.2f}",
            action="stop_loss",
        )
    return None


async def check_take_profit(
    session: AsyncSession,
    account: TradingAccount,
    position: Position,
    current_price: float,
) -> list[TradeLog]:
    """Check mixed take-profit. Returns list of trade logs for any sells."""
    logs: list[TradeLog] = []
    gain_pct = (current_price - position.avg_cost) / position.avg_cost

    # Fixed ratio: +15% sell 1/3, +30% sell 1/3
    # Use tier to track which take-profit levels have been hit
    # We'll encode take_profit_step in the reason for simplicity

    # Check if we have already taken profit at specific levels
    async def _already_sold_at(level: str) -> bool:
        stmt = select(func.count(TradeLog.id)).where(
            and_(
                TradeLog.account_id == account.id,
                TradeLog.code == position.code,
                TradeLog.action == "take_profit",
                TradeLog.reason.contains(level),
            )
        )
        result = await session.execute(stmt)
        return (result.scalar_one_or_none() or 0) > 0

    # +30% take profit (check first since it's higher)
    if gain_pct >= 0.30 and not await _already_sold_at("+30%"):
        sell_shares = max(100, int(position.shares / 3 / 100) * 100)
        if sell_shares > 0 and sell_shares <= position.shares:
            log = await execute_sell(
                session, account, position, current_price,
                reason="固定止盈+30% 卖出1/3",
                action="take_profit",
                shares=sell_shares,
            )
            if log:
                logs.append(log)

    # +15% take profit
    elif gain_pct >= 0.15 and not await _already_sold_at("+15%"):
        sell_shares = max(100, int(position.shares / 3 / 100) * 100)
        if sell_shares > 0 and sell_shares <= position.shares:
            log = await execute_sell(
                session, account, position, current_price,
                reason="固定止盈+15% 卖出1/3",
                action="take_profit",
                shares=sell_shares,
            )
            if log:
                logs.append(log)

    # Trailing stop: if current price drops 5% from high_since_open
    if position.high_since_open > 0:
        drawdown = (position.high_since_open - current_price) / position.high_since_open
        if drawdown >= 0.05 and gain_pct > 0:
            log = await execute_sell(
                session, account, position, current_price,
                reason=f"追踪止盈 回撤={drawdown:.1%} 最高={position.high_since_open:.2f}",
                action="take_profit",
            )
            if log:
                logs.append(log)

    return logs


# ======================================================================
# Update trailing state
# ======================================================================

async def update_trailing_state(session: AsyncSession, position: Position) -> None:
    """Update high_since_open and trailing stop_loss_price."""
    latest_high = await get_latest_high(session, position.code)
    if latest_high and latest_high > position.high_since_open:
        position.high_since_open = latest_high

    # Recalculate trailing stop loss (only move up)
    atr = await compute_atr(session, position.code)
    if atr:
        latest_price = await get_latest_price(session, position.code)
        if latest_price:
            new_stop = round(latest_price - 2 * atr, 2)
            if new_stop > position.stop_loss_price:
                position.stop_loss_price = new_stop
                logger.debug(f"Trailing stop updated for {position.code}: {new_stop:.2f}")


# ======================================================================
# Account value update
# ======================================================================

async def update_account_value(session: AsyncSession, account: TradingAccount) -> dict:
    """Recalculate account total value from cash + positions."""
    stmt = select(Position).where(Position.account_id == account.id)
    result = await session.execute(stmt)
    positions = result.scalars().all()

    if not positions:
        account.total_value = round(account.cash, 2)
        account.updated_at = datetime.now()
        return {
            "total_value": account.total_value,
            "cash": round(account.cash, 2),
            "position_value": 0.0,
            "pnl": round(account.total_value - account.initial_capital, 2),
            "pnl_pct": round((account.total_value / account.initial_capital - 1) * 100, 2),
        }

    # Fetch live prices for accurate valuation
    codes = [pos.code for pos in positions]
    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()
    live_prices = await loop.run_in_executor(None, refresh_live_prices, codes)

    position_value = 0.0
    for pos in positions:
        price = live_prices.get(pos.code) or await get_latest_price(session, pos.code)
        if price:
            position_value += price * pos.shares

    account.total_value = round(account.cash + position_value, 2)
    account.updated_at = datetime.now()

    return {
        "total_value": account.total_value,
        "cash": round(account.cash, 2),
        "position_value": round(position_value, 2),
        "pnl": round(account.total_value - account.initial_capital, 2),
        "pnl_pct": round((account.total_value / account.initial_capital - 1) * 100, 2),
    }


# ======================================================================
# Get positions with current prices
# ======================================================================

async def get_positions_with_prices(session: AsyncSession, account_id: int) -> list[dict]:
    """Get all positions enriched with current prices."""
    stmt = select(Position).where(Position.account_id == account_id)
    result = await session.execute(stmt)
    positions = result.scalars().all()

    if not positions:
        return []

    codes = [pos.code for pos in positions]
    price_map: dict[str, float] = {}

    # Try Redis cache first
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        cached = await redis.mget([f"price:{c}" for c in codes])
        price_map = {codes[i]: float(cached[i]) for i in range(len(codes)) if cached[i]}
    except Exception:
        pass

    # If any codes missing from cache, fetch live prices from Tencent
    missing = [c for c in codes if c not in price_map]
    if missing:
        import asyncio as _asyncio
        loop = _asyncio.get_running_loop()
        live_prices = await loop.run_in_executor(None, refresh_live_prices, missing)
        price_map.update(live_prices)

    records = []
    for pos in positions:
        current_price = price_map.get(pos.code) or await get_latest_price(session, pos.code) or pos.avg_cost
        pnl = (current_price - pos.avg_cost) * pos.shares
        pnl_pct = (current_price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0

        records.append({
            "code": pos.code,
            "name": pos.name,
            "shares": pos.shares,
            "avg_cost": round(pos.avg_cost, 2),
            "current_price": round(current_price, 2),
            "market_value": round(current_price * pos.shares, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "stop_loss_price": round(pos.stop_loss_price, 2),
            "tier": pos.tier,
            "created_at": str(pos.created_at),
        })

    return records


def refresh_live_prices(codes: list[str]) -> dict[str, float]:
    """Fetch live prices from Tencent and store in Redis. Call from background thread."""
    import requests as req
    import redis as sync_redis
    from app.core.config import settings

    prefixed = []
    for code in codes:
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
        prefixed.append(f"{prefix}{code}")

    prices = {}
    try:
        url = f"http://qt.gtimg.cn/q={','.join(prefixed)}"
        r = req.get(url, timeout=5)
        text = r.content.decode("gbk", errors="replace")
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            fields = line.split("~")
            if len(fields) > 3:
                code = fields[2]
                close = float(fields[3]) if fields[3] else 0
                if code and close > 0:
                    prices[code] = close

        # Write to Redis with 60s TTL
        rds = sync_redis.from_url(settings.redis_url, decode_responses=True)
        pipe = rds.pipeline()
        for code, price in prices.items():
            pipe.set(f"price:{code}", price, ex=60)
        pipe.execute()
        rds.close()
    except Exception:
        pass

    return prices


# ======================================================================
# Trading log query
# ======================================================================

async def get_trade_logs(
    session: AsyncSession,
    account_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Get paginated trade logs, newest first."""
    base_filter = TradeLog.account_id == account_id

    count_stmt = select(func.count(TradeLog.id)).where(base_filter)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one_or_none() or 0

    stmt = (
        select(TradeLog)
        .where(base_filter)
        .order_by(TradeLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    records = []
    for r in rows:
        records.append({
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "action": r.action,
            "shares": r.shares,
            "price": round(r.price, 2),
            "amount": round(r.amount, 2),
            "pnl": round(r.pnl, 2) if r.pnl is not None else None,
            "reason": r.reason,
            "created_at": str(r.created_at),
        })

    return records, total


# ======================================================================
# Daily scheduled tasks
# ======================================================================

async def pre_market_check(session: AsyncSession) -> list[dict]:
    """Run before market open: check rankings, plan buys/sells."""
    actions = []

    account = await get_or_create_account(session)
    if not account.is_active:
        return actions

    today = date.today()
    strategy = strategy_loader.active_name

    # Get today's rankings, fallback to most recent available date
    from app.services.ranking_service import get_ranking_list
    records, _ = await get_ranking_list(session, today, page=1, page_size=20, strategy=strategy)

    if not records:
        # Fallback: use most recent ranking date
        latest_date_stmt = (
            select(func.max(StockRanking.rank_date))
            .where(StockRanking.strategy == strategy)
        )
        latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
        if latest_date:
            logger.info(f"No rankings for {today}, falling back to {latest_date}")
            records, _ = await get_ranking_list(session, latest_date, page=1, page_size=20, strategy=strategy)

    if not records:
        logger.warning("No rankings available for trading")
        return actions

    # Get current positions
    stmt = select(Position).where(Position.account_id == account.id)
    result = await session.execute(stmt)
    existing = {p.code: p for p in result.scalars().all()}

    # Daily: sell positions not in current top 10
    top10_codes = {r["code"] for r in records[:10]}
    for code, pos in list(existing.items()):
        if code not in top10_codes:
            price = await get_latest_price(session, code) or pos.avg_cost
            log = await execute_sell(
                session, account, pos, price,
                reason=f"调仓 排名跌出前10",
            )
            del existing[code]
            actions.append({"action": "sell", "code": code, "name": pos.name, "reason": "调仓"})

    # Check pyramid add conditions for existing positions
    for code, pos in existing.items():
        price = await get_latest_price(session, code)
        if price:
            await check_and_execute_pyramid_add(session, account, pos, price)

    # Buy new positions: top 10 not yet held, skip ST stocks
    for r in records[:10]:
        if r["code"] in existing:
            continue
        if len(existing) + sum(1 for a in actions if a.get("action") == "buy") >= 10:
            break

        name = r.get("name", "")
        if not name:
            name_stmt = select(StockInfo.name).where(StockInfo.code == r["code"])
            name_result = await session.execute(name_stmt)
            name = name_result.scalar_one_or_none() or r["code"]
        if "ST" in name.upper():
            logger.info(f"Skipping ST stock {r['code']} {name}")
            continue

        price = await get_latest_price(session, r["code"])
        if not price or price <= 0:
            continue

        atr = await compute_atr(session, r["code"])
        if not atr:
            continue

        log = await execute_buy(
            session, account, r["code"], name, r["rank"], price, atr,
        )
        if log:
            actions.append({"action": "buy", "code": r["code"], "name": name, "rank": r["rank"]})

    await session.commit()
    return actions


async def realtime_check(session: AsyncSession) -> list[dict]:
    """Run during market hours: check stop-loss and take-profit."""
    actions = []

    account = await get_or_create_account(session)
    if not account.is_active:
        return actions

    stmt = select(Position).where(Position.account_id == account.id)
    result = await session.execute(stmt)
    positions = result.scalars().all()

    for pos in positions:
        price = await get_latest_price(session, pos.code)
        if not price or price <= 0:
            continue

        # Check stop-loss
        log = await check_stop_loss(session, account, pos, price)
        if log:
            actions.append({"action": "stop_loss", "code": pos.code, "name": pos.name, "price": price})
            continue  # Position deleted

        # Check take-profit
        tp_logs = await check_take_profit(session, account, pos, price)
        for tp_log in tp_logs:
            actions.append({"action": "take_profit", "code": pos.code, "name": pos.name, "price": price})

        # Update trailing state
        await update_trailing_state(session, pos)

    if actions:
        await session.commit()

    return actions


async def post_market_update(session: AsyncSession) -> dict | None:
    """Run after market close: update trailing stops, account value, return summary."""
    account = await get_or_create_account(session)
    if not account.is_active:
        return None

    stmt = select(Position).where(Position.account_id == account.id)
    result = await session.execute(stmt)
    positions = result.scalars().all()

    for pos in positions:
        await update_trailing_state(session, pos)

    value_info = await update_account_value(session, account)
    await session.commit()

    return value_info


# ======================================================================
# Start / Stop / Reset
# ======================================================================

async def start_bot(session: AsyncSession) -> dict:
    """Start the trading bot."""
    account = await get_or_create_account(session)
    account.is_active = True
    await session.commit()
    logger.info("Trading bot started")
    return {"status": "started", "is_active": True}


async def stop_bot(session: AsyncSession) -> dict:
    """Stop the trading bot."""
    account = await get_or_create_account(session)
    account.is_active = False
    await session.commit()
    logger.info("Trading bot stopped")
    return {"status": "stopped", "is_active": False}


async def reset_account(session: AsyncSession) -> dict:
    """Reset trading account: clear all positions and logs."""
    account = await get_or_create_account(session)

    # Delete all positions
    from sqlalchemy import delete as sql_delete
    await session.execute(sql_delete(Position).where(Position.account_id == account.id))
    await session.execute(sql_delete(TradeLog).where(TradeLog.account_id == account.id))

    account.cash = account.initial_capital
    account.total_value = account.initial_capital
    account.is_active = False
    await session.commit()

    logger.info("Trading account reset")
    return {"status": "reset", "cash": account.cash, "total_value": account.total_value}


# ======================================================================
# WeChat Work notifications for trading
# ======================================================================

async def send_trading_notification(title: str, actions: list[dict]) -> None:
    """Send trading actions to WeChat Work."""
    if not actions:
        return

    from app.core.config import settings
    from app.services.notification_service import send_wechat_work

    if not settings.wechat_webhook_url:
        return

    action_labels = {
        "buy": "🟢 买入", "sell": "🔴 卖出",
        "stop_loss": "⚠️ 止损", "take_profit": "💰 止盈",
    }

    lines = [f"## 🤖 模拟交易 - {title}", ""]
    for a in actions:
        label = action_labels.get(a.get("action", ""), a.get("action", ""))
        name = a.get("name", a.get("code", ""))
        detail = f" @ {a['price']:.2f}" if a.get("price") else ""
        reason = f" ({a['reason']})" if a.get("reason") else ""
        lines.append(f"- {label} **{name}**{detail}{reason}")

    lines.append("")
    send_wechat_work(settings.wechat_webhook_url, "\n".join(lines))


async def send_trading_summary(value_info: dict) -> None:
    """Send daily trading summary to WeChat Work."""
    from app.core.config import settings
    from app.services.notification_service import send_wechat_work

    if not settings.wechat_webhook_url:
        return

    pnl = value_info.get("pnl", 0)
    pnl_pct = value_info.get("pnl_pct", 0)
    arrow = "🔴" if pnl < 0 else "🟢"

    lines = [
        "## 📊 模拟交易日报",
        "",
        f"{arrow} **总资产** ¥{value_info['total_value']:,.2f}",
        f"- 可用资金 ¥{value_info['cash']:,.2f}",
        f"- 持仓市值 ¥{value_info['position_value']:,.2f}",
        f"- 累计盈亏 ¥{pnl:+,.2f} ({pnl_pct:+.2f}%)",
        "",
    ]

    send_wechat_work(settings.wechat_webhook_url, "\n".join(lines))
