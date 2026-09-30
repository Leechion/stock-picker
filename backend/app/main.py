from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.database import Base, engine
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor, wechat, alerts, ai_picks, jobs, quotes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.core.logging import setup_logging
    from app.core.scheduler import register_scheduler, shutdown_scheduler

    setup_logging()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    register_scheduler()

    from app.core.websocket import monitor_hub
    monitor_hub.start_broadcast_loop()

    # Realtime quote poller: keeps the whole market fresh in Redis during
    # trading hours and pushes deltas on the `quotes` WS channel.
    from app.services import daily_archiver, quote_poller
    quote_poller.start_poller()
    # Keeps today's stock_daily bar current during the session (every 5 min),
    # so factors and the screener are not stuck on yesterday's data until 15:05.
    daily_archiver.start_archiver()

    # Warm the quote cache immediately so the first page load has data even
    # outside trading hours (upstream still returns the last close).
    import asyncio as _asyncio

    async def _warm_quotes():
        await _asyncio.sleep(2)
        try:
            quotes = await quote_poller.refresh_once()
            logger.info(f"Startup: warmed {len(quotes)} realtime quotes")
        except Exception as e:
            logger.warning(f"Startup quote warm failed: {e}")

    _asyncio.create_task(_warm_quotes())

    # Refresh live prices on startup if there are open positions
    async def _startup_price_refresh():
        await _asyncio.sleep(1)
        try:
            from app.services.trading_service import get_account, refresh_live_prices
            from app.models.trading import Position
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                account = await get_account(session)
                if account is None:
                    return
                stmt = select(Position.code).where(Position.account_id == account.id)
                result = await session.execute(stmt)
                codes = list(result.scalars().all())
                if codes:
                    refresh_live_prices(codes)
                    logger.info(f"Startup: cached {len(codes)} live prices to Redis")
        except Exception as e:
            logger.warning(f"Startup price refresh failed: {e}")

    _asyncio.create_task(_startup_price_refresh())

    try:
        yield
    finally:
        logger.info("Shutting down...")

        from app.services.data_service import shutdown_event as _shutdown_event
        _shutdown_event.set()

        from app.services import daily_archiver as _da
        from app.services import quote_poller as _qp
        await _qp.stop_poller()
        await _da.stop_archiver()

        from app.core.websocket import monitor_hub
        await monitor_hub.stop_broadcast_loop()
        shutdown_scheduler()

        try:
            await engine.dispose()
        except Exception:
            pass

        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="QuantBlade",
        version="0.1.0",
        description="量剑 - A股量化多因子选股平台",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(stocks.router, prefix="/api")
    app.include_router(factors.router, prefix="/api")
    app.include_router(ranking.router, prefix="/api")
    app.include_router(strategy.router, prefix="/api")
    app.include_router(sectors.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(trading.router, prefix="/api")
    app.include_router(monitor.router, prefix="/api")
    app.include_router(wechat.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")
    app.include_router(ai_picks.router, prefix="/api")
    # Job routes must be registered BEFORE ranking.router so that
    # `/jobs/...` is not shadowed by ranking's catch-all `/rankings/{code}`.
    app.include_router(jobs.router, prefix="/api")
    app.include_router(quotes.router, prefix="/api")

    return app


app = create_app()
