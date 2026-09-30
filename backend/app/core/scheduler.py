from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.services.data_service import sync_all_stocks, sync_fundamentals
from app.services.notification_service import send_daily_notification
from app.services.ai_pick_service import run_ai_pick_task, backtest_ai_picks_open, backtest_ai_picks_close

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
    """Scheduled factor + ranking + alert run.

    Delegates to the shared pipeline instead of re-implementing the sequence.
    This function previously carried its own copy of the pipeline, which had
    drifted from the identical copy in ``app/api/ranking.py`` — the API copy
    shared one ``AsyncSession`` across workers and crashed, while this one had
    been fixed. One implementation, one place to fix.

    Failures are logged and swallowed because a scheduler job must not raise
    into APScheduler.
    """
    logger.info("Starting daily ranking computation")
    from app.core.jobs import JobContext
    from app.pipelines import run_full_ranking_pipeline

    ctx = JobContext(job_id=0, job_type="scheduled_ranking", params={})
    try:
        result = await run_full_ranking_pipeline(ctx, trading_date=date.today())
        logger.info(
            f"Daily ranking: {result['rankings'].get('stocks_computed', 0)} stocks ranked, "
            f"{result['factors'].get('factors_written', 0)} factor rows, "
            f"{result['alerts_triggered']} alerts"
        )
    except Exception as e:
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
    # AI tomorrow pick jobs
    scheduler.add_job(
        run_ai_pick_task,
        trigger="cron",
        hour=14,
        minute=30,
        day_of_week="mon-fri",
        id="ai_pick",
        name="AI pick for tomorrow",
        replace_existing=True,
    )
    scheduler.add_job(
        backtest_ai_picks_open,
        trigger="cron",
        hour=9,
        minute=26,
        day_of_week="mon-fri",
        id="ai_pick_backtest_open",
        name="Backtest AI picks - open price",
        replace_existing=True,
    )
    scheduler.add_job(
        backtest_ai_picks_close,
        trigger="cron",
        hour=15,
        minute=5,
        day_of_week="mon-fri",
        id="ai_pick_backtest_close",
        name="Backtest AI picks - close price",
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
