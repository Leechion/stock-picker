import os
from pathlib import Path

TEST_DB_PATH = Path("./test_stock_picker.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import create_app


BASE_URL = "http://test"


def _create_test_app() -> FastAPI:
    app = create_app()
    return app


@pytest_asyncio.fixture
async def session():
    TEST_DB_PATH.unlink(missing_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB_PATH}", echo=False)
    from app.core.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.commit()

    await engine.dispose()
    TEST_DB_PATH.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client(session):
    app = _create_test_app()

    from app.core.database import get_db

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as ac:
        yield ac

    app.dependency_overrides.clear()
