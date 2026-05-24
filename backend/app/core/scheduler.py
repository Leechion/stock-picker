from datetime import date

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
            # Step 1: Load all stock codes
            from sqlalchemy import select
            result = await session.execute(select(StockInfo.code))
            codes = list(result.scalars().all())

            # Step 2: Compute factors for each stock
            computed = 0
            for code in codes:
                df = await get_history(session, code, days=250)
                if not df.empty:
                    await compute_all_factors(session, code, df)
                    computed += 1

            # Step 3: Compute rankings for all strategies
            from app.services.ranking_service import compute_all_rankings
            ranking_result = await compute_all_rankings(session, date.today())
            logger.info(f"Daily ranking: {ranking_result.get('stocks_computed', 0)} stocks ranked")

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
                from app.services.trading_service import send_trading_summary
                await send_trading_summary(result)
        except Exception as e:
            logger.error(f"Post-market update failed: {e}")


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
        minute=10,
        day_of_week="mon-fri",
        id="daily_ranking",
        name="Daily stock ranking compute",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_notification,
        trigger="cron",
        hour=15,
        minute=12,
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
        run_post_market_update,
        trigger="cron",
        hour=15,
        minute=7,
        day_of_week="mon-fri",
        id="trading_post_market",
        name="Post-market trading update",
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
