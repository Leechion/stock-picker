from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.database import Base, engine
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor, wechat


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

    # Refresh live prices on startup if there are open positions
    import asyncio as _asyncio

    async def _startup_price_refresh():
        await _asyncio.sleep(1)
        try:
            from app.services.trading_service import get_or_create_account, refresh_live_prices
            from app.models.trading import Position
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                account = await get_or_create_account(session)
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

        from app.core.websocket import monitor_hub
        await monitor_hub.stop_broadcast_loop()
        shutdown_scheduler()

        # Dispose DB engine first, while internal tasks are still alive
        try:
            await engine.dispose()
        except Exception:
            pass

        # Cancel remaining user tasks with a short timeout
        current = _asyncio.current_task()
        tasks = [t for t in _asyncio.all_tasks() if t is not current]
        for t in tasks:
            t.cancel()
        if tasks:
            try:
                await _asyncio.wait_for(_asyncio.gather(*tasks, return_exceptions=True), timeout=3)
            except (TimeoutError, _asyncio.CancelledError):
                pass

        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="智能选股系统",
        version="0.1.0",
        description="A股量化多因子选股平台",
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

    return app


app = create_app()
