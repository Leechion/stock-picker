"""Alembic environment for QuantBlade.

Migrations are run with a *synchronous* engine. The application uses the async
driver (`sqlite+aiosqlite://`), so the URL is normalised to `sqlite://` here.
Running migrations synchronously keeps the setup simple and reliable — no event
loop juggling inside Alembic, and SQLite migrations are not concurrent anyway.

URL resolution order (first match wins):
  1. `-x db_url=...`  (e.g. `alembic -x db_url=sqlite:////tmp/x.db upgrade head`)
  2. `DATABASE_URL` environment variable
  3. `settings.database_url` from app/core/config.py (reads backend/.env)
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Make the `app` package importable when alembic runs from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  (imports every model so metadata is complete)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _to_sync_url(url: str) -> str:
    """Rewrite an async SQLAlchemy URL to its synchronous equivalent."""
    replacements = {
        "sqlite+aiosqlite": "sqlite",
        "postgresql+asyncpg": "postgresql+psycopg2",
        "mysql+aiomysql": "mysql+pymysql",
    }
    for async_prefix, sync_prefix in replacements.items():
        if url.startswith(async_prefix):
            return sync_prefix + url[len(async_prefix):]
    return url


def get_url() -> str:
    """Resolve the database URL (see module docstring for precedence)."""
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_url"):
        return _to_sync_url(x_args["db_url"])

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return _to_sync_url(env_url)

    from app.core.config import settings

    return _to_sync_url(settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DB connection)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things; batch mode recreates tables.
            render_as_batch=True,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
