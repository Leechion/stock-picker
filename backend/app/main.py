from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import Base, engine
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.core.logging import setup_logging
    from app.core.scheduler import register_scheduler, shutdown_scheduler

    setup_logging()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    register_scheduler()

    try:
        yield
    finally:
        shutdown_scheduler()


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

    return app


app = create_app()
