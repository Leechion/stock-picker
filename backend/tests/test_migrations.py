"""Tests for the Alembic baseline migration.

These tests run ``alembic upgrade head`` / ``downgrade base`` against a
throwaway SQLite database in a temporary directory. They never touch the
development database: the URL is passed explicitly via ``-x db_url=...``, which
takes precedence over both ``DATABASE_URL`` and ``backend/.env``.

Alembic is invoked as ``python -m alembic`` (not the ``.venv/bin/alembic``
console script) because this virtualenv was created at a different path and its
console-script shebangs are stale.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Every table declared in app/models/ (stock.py, trading.py, alert.py, ai_pick.py, job.py).
EXPECTED_TABLES = {
    # app/models/stock.py
    "stocks",
    "stock_daily",
    "factor_values",
    "stock_fundamentals",
    "stock_rankings",
    # app/models/trading.py
    "trading_accounts",
    "trading_positions",
    "trading_logs",
    # app/models/alert.py
    "alert_rules",
    "alert_logs",
    # app/models/ai_pick.py
    "ai_picks",
    # app/models/job.py
    "jobs",
}


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run an alembic command against an explicit, isolated database."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            f"db_url=sqlite:///{db_path}",
            *args,
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )


def _tables(db_path: Path) -> set[str]:
    """Application tables present in the database (excludes alembic's own)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")} - {"alembic_version"}


def _revision(db_path: Path) -> str | None:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        con.close()
    return row[0] if row else None


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Path to a fresh, empty SQLite database."""
    return tmp_path / "migrations_test.db"


def test_upgrade_head_on_empty_db_creates_all_model_tables(temp_db: Path) -> None:
    """`alembic upgrade head` on a brand-new database creates every model table."""
    assert not temp_db.exists() or _tables(temp_db) == set()

    result = _run_alembic(temp_db, "upgrade", "head")

    assert result.returncode == 0, f"upgrade failed:\n{result.stdout}\n{result.stderr}"
    assert "Running upgrade" in result.stderr

    created = _tables(temp_db)
    assert created == EXPECTED_TABLES, (
        f"missing: {sorted(EXPECTED_TABLES - created)}, "
        f"unexpected: {sorted(created - EXPECTED_TABLES)}"
    )
    assert _revision(temp_db) == "0002"


def test_downgrade_base_removes_all_tables(temp_db: Path) -> None:
    """`alembic downgrade base` empties the schema created by the baseline."""
    assert _run_alembic(temp_db, "upgrade", "head").returncode == 0
    assert _tables(temp_db) == EXPECTED_TABLES

    result = _run_alembic(temp_db, "downgrade", "base")

    assert result.returncode == 0, f"downgrade failed:\n{result.stdout}\n{result.stderr}"
    assert "Running downgrade" in result.stderr
    assert _tables(temp_db) == set()
    assert _revision(temp_db) is None


def test_upgrade_downgrade_upgrade_round_trip(temp_db: Path) -> None:
    """The baseline is repeatable: up -> down -> up yields the same schema."""
    assert _run_alembic(temp_db, "upgrade", "head").returncode == 0
    assert _run_alembic(temp_db, "downgrade", "base").returncode == 0
    assert _tables(temp_db) == set()

    assert _run_alembic(temp_db, "upgrade", "head").returncode == 0
    assert _tables(temp_db) == EXPECTED_TABLES
    assert _revision(temp_db) == "0002"


def test_upgrade_is_idempotent_when_tables_already_exist(temp_db: Path) -> None:
    """A database already populated by create_all can be stamped safely.

    ``upgrade()`` skips tables that already exist, so an accidental upgrade
    against a pre-existing schema does not fail or destroy data.
    """
    # Simulate a legacy database created by Base.metadata.create_all.
    sys.path.insert(0, str(BACKEND_DIR))
    from app.core.database import Base  # noqa: PLC0415
    import app.models  # noqa: PLC0415,F401
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(engine)
    engine.dispose()

    assert _tables(temp_db) == EXPECTED_TABLES

    # Running the baseline against it must not raise.
    result = _run_alembic(temp_db, "upgrade", "head")
    assert result.returncode == 0, f"upgrade on populated db failed:\n{result.stderr}"
    assert _tables(temp_db) == EXPECTED_TABLES


def test_migration_covers_exact_orm_metadata(temp_db: Path) -> None:
    """The baseline table set matches the ORM metadata exactly (no drift)."""
    sys.path.insert(0, str(BACKEND_DIR))
    from app.core.database import Base  # noqa: PLC0415
    import app.models  # noqa: PLC0415,F401

    orm_tables = set(Base.metadata.tables)
    assert EXPECTED_TABLES == orm_tables, (
        "EXPECTED_TABLES is out of sync with app/models: "
        f"only in test={sorted(EXPECTED_TABLES - orm_tables)}, "
        f"only in ORM={sorted(orm_tables - EXPECTED_TABLES)}"
    )

    assert _run_alembic(temp_db, "upgrade", "head").returncode == 0

    # Column-level comparison, so a model column added without a migration fails.
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    engine = create_engine(f"sqlite:///{temp_db}")
    insp = inspect(engine)
    try:
        for table in sorted(orm_tables):
            migrated = {c["name"] for c in insp.get_columns(table)}
            expected = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated == expected, (
                f"{table}: missing={sorted(expected - migrated)}, "
                f"extra={sorted(migrated - expected)}"
            )
    finally:
        engine.dispose()
