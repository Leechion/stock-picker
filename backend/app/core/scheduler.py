from datetime import date

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.models.stock import StockInfo
from app.services.data_service import sync_all_stocks, get_history, sync_fundamentals
from app.services.factor_engine import compute_all_factors
from app.services.notification_service import send_daily_notification

scheduler: AsyncIOScheduler | None = None


async def run_daily_sync() -> None:
    logger.info("Starting daily data sync")
    async with AsyncSessionLocal() as session:
        try:
            count = await sync_all_stocks(session)
            logger.info(f"Daily sync synced {count} stocks")
        except Exception as e:
            logger.error(f"Daily sync failed: {e}")


async def run_daily_ranking() -> None:
    logger.info("Starting daily ranking computation")
    async with AsyncSessionLocal() as session:
        try:
            # Step 1: Load all stock codes (exclude ST and price > 100)
            from sqlalchemy import select
            from app.services.ranking_service import get_eligible_codes
            eligible = await get_eligible_codes(session)
            codes = sorted(eligible)
            logger.info(f"Eligible stocks for ranking: {len(codes)} (excluded ST & price>100)")

            # Step 2: Compute factors for each stock (concurrent)
            import asyncio
            from app.services.capital_flow import fetch_flow_and_chip
            from app.services.factor_engine import compute_factors_for_stock
            from app.models.stock import StockFundamental, FactorValue, StockInfo as SI
            from sqlalchemy import delete as sql_delete, insert, func

            sem = asyncio.Semaphore(20)

            # Pre-load sector heat map
            sector_heat_map: dict[str, float] = {}
            try:
                from app.services import sector_service
                loop = asyncio.get_running_loop()
                sectors = await loop.run_in_executor(None, sector_service.fetch_sector_performance)
                if sectors:
                    sector_heat_map = await loop.run_in_executor(None, sector_service.compute_sector_heat, sectors)
            except Exception:
                pass

            # Pre-load all fundamentals and industries in one query
            fund_rows = (await session.execute(select(StockFundamental))).scalars().all()
            fund_map = {r.code: r for r in fund_rows}

            info_rows = (await session.execute(select(SI.code, SI.industry))).all()
            industry_map = {code: ind for code, ind in info_rows}

            async def process_one(code: str) -> list[dict]:
                async with sem:
                    df = await get_history(session, code, days=80)
                    if df.empty:
                        return []

                    loop = asyncio.get_running_loop()
                    flow_data = await loop.run_in_executor(None, lambda c=code: fetch_flow_and_chip(c))

                    fundamentals = None
                    fr = fund_map.get(code)
                    if fr:
                        fundamentals = {
                            "pe_ttm": fr.pe_ttm, "pb": fr.pb, "roe": fr.roe,
                            "revenue_growth": fr.revenue_growth,
                            "profit_growth": fr.profit_growth,
                            "debt_ratio": fr.debt_ratio,
                        }

                    sector_heat = sector_heat_map.get(industry_map.get(code, ""))
                    raw = compute_factors_for_stock(df, code, fundamentals, flow_data, sector_heat)
                    return raw

            tasks = [process_one(code) for code in codes]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Batch insert factor values
            now = pd.Timestamp.now()
            all_records = []
            computed = 0
            for i, raw in enumerate(results):
                if isinstance(raw, Exception):
                    logger.debug(f"Factor compute failed for {codes[i]}: {raw}")
                    continue
                if not raw:
                    continue
                for f in raw:
                    all_records.append({
                        "code": codes[i],
                        "factor_name": f["factor_name"],
                        "factor_type": f["factor_type"],
                        "value": f["value"],
                        "computed_at": now,
                    })
                computed += 1

            # Delete old factors and batch insert new (only if we have new data)
            if all_records:
                await session.execute(sql_delete(FactorValue))
                for i in range(0, len(all_records), 500):
                    await session.execute(insert(FactorValue), all_records[i:i + 500])
                await session.commit()
            else:
                logger.warning("No factor records computed, skipping delete/insert")

            logger.info(f"Factors computed: {computed}/{len(codes)} stocks")

            # Step 3: Compute rankings for all strategies
            from app.services.ranking_service import compute_all_rankings
            ranking_result = await compute_all_rankings(session, date.today())
            logger.info(f"Daily ranking: {ranking_result.get('stocks_computed', 0)} stocks ranked")

            # Step 4: Check alert rules
            from app.services.alert_service import check_alerts, format_alert_message
            triggers = await check_alerts(session)
            if triggers:
                logger.info(f"Alert triggers: {len(triggers)}")
                message = format_alert_message(triggers)
                if message:
                    from app.services.notification_service import send_wechat_work
                    from app.core.config import settings
                    send_wechat_work(settings.wechat_webhook_url, message)
            else:
                logger.info("No alert triggers")

        except Exception as e:
            await session.rollback()
            logger.error(f"Daily ranking failed: {e}")


async def run_pre_market_check() -> None:
    """Pre-market check: plan buys/sells based on rankings."""
    logger.info("Running pre-market trading check")
    async with AsyncSessionLocal() as session:
        try:
            from app.services.trading_service import pre_market_check
            actions = await pre_market_check(session)
            if actions:
                logger.info(f"Pre-market actions: {len(actions)}")
                from app.services.trading_service import send_trading_notification
                await send_trading_notification("开盘前检查", actions)
        except Exception as e:
            logger.error(f"Pre-market check failed: {e}")


async def run_realtime_check() -> None:
    """Real-time check: stop-loss and take-profit during market hours."""
    async with AsyncSessionLocal() as session:
        try:
            from app.services.trading_service import realtime_check
            actions = await realtime_check(session)
            if actions:
                logger.info(f"Realtime check actions: {len(actions)}")
                from app.services.trading_service import send_trading_notification
                await send_trading_notification("盘中监控", actions)
        except Exception as e:
            logger.error(f"Realtime check failed: {e}")


async def run_post_market_update() -> None:
    """Post-market update: trailing stops, account value."""
    logger.info("Running post-market trading update")
    async with AsyncSessionLocal() as session:
        try:
            from app.services.trading_service import post_market_update
            result = await post_market_update(session)
            if result:
                logger.info(f"Post-market: total_value={result['total_value']:.2f}")
        except Exception as e:
            logger.error(f"Post-market update failed: {e}")


async def run_refresh_live_prices() -> None:
    """Refresh live prices for held positions."""
    async with AsyncSessionLocal() as session:
        try:
            import asyncio
            from app.services.trading_service import get_account, refresh_live_prices
            from app.models.trading import Position
            from sqlalchemy import select

            account = await get_account(session)
            if account is None:
                return
            stmt = select(Position.code).where(Position.account_id == account.id)
            result = await session.execute(stmt)
            codes = list(result.scalars().all())
            if codes:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, refresh_live_prices, codes)
        except Exception as e:
            logger.error(f"Refresh live prices failed: {e}")


async def run_daily_summary() -> None:
    """Daily summary: calculate P&L with real closing prices and send to WeChat."""
    logger.info("Running daily trading summary")
    async with AsyncSessionLocal() as session:
        try:
            import asyncio
            from sqlalchemy import select
            from app.services.trading_service import get_account, refresh_live_prices
            from app.models.trading import Position

            account = await get_account(session)
            if account is None:
                logger.info("No trading account, skipping daily summary")
                return
            stmt = select(Position).where(Position.account_id == account.id)
            result = await session.execute(stmt)
            positions = result.scalars().all()

            if not positions:
                logger.info("No positions, skipping daily summary")
                return

            # Fetch real closing prices
            codes = [p.code for p in positions]
            loop = asyncio.get_running_loop()
            close_prices = await loop.run_in_executor(None, refresh_live_prices, codes)

            # Build message
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
            send_wechat_work(settings.wechat_webhook_url, msg)
            logger.info("Daily summary sent to WeChat")
        except Exception as e:
            logger.error(f"Daily summary failed: {e}")


async def run_weekly_fundamental_sync() -> None:
    logger.info("Starting weekly fundamental sync")
    async with AsyncSessionLocal() as session:
        try:
            count = await sync_fundamentals(session)
            logger.info(f"Weekly fundamental sync: {count} stocks synced")
        except Exception as e:
            logger.error(f"Weekly fundamental sync failed: {e}")


async def run_daily_notification() -> None:
    logger.info("Sending daily ranking notification")
    try:
        sent = await send_daily_notification()
        if sent:
            logger.info("Daily notification sent successfully")
        else:
            logger.warning("Daily notification not sent (check config)")
    except Exception as e:
        logger.error(f"Daily notification failed: {e}")


def register_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        return

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_daily_sync,
        trigger="cron",
        hour=15,
        minute=5,
        day_of_week="mon-fri",
        id="daily_sync",
        name="Daily stock data sync",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_ranking,
        trigger="cron",
        hour=15,
        minute=25,
        day_of_week="mon-fri",
        id="daily_ranking",
        name="Daily stock ranking compute",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_notification,
        trigger="cron",
        hour=15,
        minute=27,
        day_of_week="mon-fri",
        id="daily_notification",
        name="Daily ranking notification push",
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekly_fundamental_sync,
        trigger="cron",
        hour=15,
        minute=15,
        day_of_week="fri",
        id="weekly_fundamental_sync",
        name="Weekly fundamental data sync",
        replace_existing=True,
    )
    # Trading bot jobs
    scheduler.add_job(
        run_pre_market_check,
        trigger="cron",
        hour=9,
        minute=25,
        day_of_week="mon-fri",
        id="trading_pre_market",
        name="Pre-market trading check",
        replace_existing=True,
    )
    scheduler.add_job(
        run_realtime_check,
        trigger="cron",
        minute="*/5",
        hour="9-14",
        day_of_week="mon-fri",
        id="trading_realtime",
        name="Realtime stop-loss/take-profit check",
        replace_existing=True,
    )
    scheduler.add_job(
        run_refresh_live_prices,
        trigger="cron",
        second="0,30",
        minute="*",
        hour="9-14",
        day_of_week="mon-fri",
        id="trading_live_prices",
        name="Refresh live prices",
        replace_existing=True,
    )
    scheduler.add_job(
        run_post_market_update,
        trigger="cron",
        hour=15,
        minute=7,
        day_of_week="mon-fri",
        id="trading_post_market",
        name="Post-market trading update",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_summary,
        trigger="cron",
        hour=15,
        minute=30,
        day_of_week="mon-fri",
        id="trading_daily_summary",
        name="Daily trading summary to WeChat",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")

def shutdown_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
    scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    return scheduler
