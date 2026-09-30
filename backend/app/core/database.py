from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

_db_url = os.getenv("DATABASE_URL", settings.database_url)

# `echo=True` logs EVERY statement to stdout via the logging module. During a
# factor run that is ~3200 stocks x several statements — the previous run wrote
# 8.5 MB of logs in 16 minutes and the I/O itself became a leading cost.
#
# So: `sql_echo` (not `debug`) controls statement logging, and it defaults to
# off even in development. Turn it on explicitly when debugging SQL.
echo_sql = bool(getattr(settings, "sql_echo", False))

engine = create_async_engine(
    _db_url,
    echo=echo_sql,
    # SQLite defaults are tuned for safety over speed. These pragmas are safe
    # for this workload (single writer, read-mostly) and meaningfully reduce
    # the cost of the bulk inserts done by the factor pipeline.
    connect_args={"timeout": 30},
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    # Keep the identity map from growing unboundedly across a long job; the
    # factor pipeline loads thousands of rows in a loop.
    autoflush=False,
)


class Base(DeclarativeBase):
    """ORM base class"""

    pass


async def get_db():
    """Dependency injector for async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
