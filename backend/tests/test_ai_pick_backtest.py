"""Tests for AI pick backtesting — trading-day resolution, idempotency, retry.

All tests are offline: they use an in-memory SQLite database and monkeypatch
``AsyncSessionLocal`` so the service never touches the real DB or the network.

Weekday reference for the fixtures:
    2026-09-25  Friday   <- pick date
    2026-09-26  Saturday (no market data — the original +1 day bug)
    2026-09-28  Monday   <- expected next trading day
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.ai_pick import AIPick
from app.models.stock import StockDaily, StockInfo
from app.services import ai_pick_service

FRIDAY = date(2026, 9, 25)
MONDAY = date(2026, 9, 28)
TUESDAY = date(2026, 9, 29)
CODE = "600519"


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_factory(monkeypatch):
    """In-memory SQLite session factory wired into the service module."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(ai_pick_service, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


async def _add_daily(factory, code: str, trade_date: date, open_p: float, close_p: float) -> None:
    async with factory() as session:
        existing = await session.execute(select(StockInfo).where(StockInfo.code == code))
        if existing.scalar_one_or_none() is None:
            session.add(StockInfo(code=code, name="贵州茅台", industry="白酒", market="main"))
            await session.flush()
        session.add(
            StockDaily(
                code=code,
                trade_date=trade_date,
                open=open_p,
                close=close_p,
                high=max(open_p, close_p),
                low=min(open_p, close_p),
                volume=1_000_000,
                amount=100_000_000,
                change_pct=0.0,
            )
        )
        await session.commit()


async def _add_pick(factory, pick_date: date, code: str = CODE, price_at_pick: float | None = None) -> int:
    async with factory() as session:
        pick = AIPick(
            pick_date=pick_date,
            code=code,
            name="贵州茅台",
            reason="test",
            confidence="high",
            price_at_pick=price_at_pick,
        )
        session.add(pick)
        await session.commit()
        return pick.id


async def _get_pick(factory, pick_id: int) -> AIPick:
    async with factory() as session:
        return (await session.execute(select(AIPick).where(AIPick.id == pick_id))).scalar_one()


# ----------------------------------------------------------------------
# (a) Friday pick must land on the following Monday, not Saturday
# ----------------------------------------------------------------------

async def test_friday_pick_uses_next_trading_day_monday(db_factory) -> None:
    """Friday 2026-09-25 + 1 day is Saturday (no data); the next real trading day is Monday."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    pick_id = await _add_pick(db_factory, FRIDAY)

    updated = await ai_pick_service.backtest_ai_picks_open()
    assert updated == 1

    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_open == 11.0, "must read Monday's open, not Saturday's"
    # price_at_pick is the pick-day close, never the next day's open.
    assert pick.price_at_pick == 10.5

    updated_close = await ai_pick_service.backtest_ai_picks_close()
    assert updated_close == 1

    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_close == 11.8
    assert pick.next_day_change_pct == pytest.approx(round((11.8 - 11.0) / 11.0 * 100, 2))
    assert pick.backtest_at is not None


async def test_close_job_works_without_open_job(db_factory) -> None:
    """backtest_close alone still produces a correct change_pct from the same day's open."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    pick_id = await _add_pick(db_factory, FRIDAY)

    assert await ai_pick_service.backtest_ai_picks_close() == 1

    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_close == 11.8
    assert pick.next_day_open == 11.0
    assert pick.next_day_change_pct == pytest.approx(round((11.8 - 11.0) / 11.0 * 100, 2))


async def test_holiday_gap_uses_first_available_trading_day(db_factory) -> None:
    """A multi-day gap (e.g. National Day holiday) resolves to the first day with data."""
    holiday_monday = date(2026, 10, 5)   # 2026-10-01..10-07 holiday
    reopen = date(2026, 10, 8)
    await _add_daily(db_factory, CODE, date(2026, 9, 30), open_p=10.0, close_p=10.2)
    await _add_daily(db_factory, CODE, reopen, open_p=10.3, close_p=10.9)
    pick_id = await _add_pick(db_factory, date(2026, 9, 30))

    assert await ai_pick_service.backtest_ai_picks_open() == 1
    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_open == 10.3
    assert pick.price_at_pick == 10.2
    assert pick.next_day_open != holiday_monday  # sanity: not a date we created


# ----------------------------------------------------------------------
# (b) No later trading day -> nothing written, row stays retryable
# ----------------------------------------------------------------------

async def test_no_next_trading_day_keeps_pick_pending(db_factory) -> None:
    """A Friday pick made before Monday's data exists must stay NULL and be retried."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    pick_id = await _add_pick(db_factory, FRIDAY)

    assert await ai_pick_service.backtest_ai_picks_open() == 0
    assert await ai_pick_service.backtest_ai_picks_close() == 0

    pick = await _get_pick(db_factory, pick_id)
    # Nothing written — not 0, not a sentinel — so a later run still selects it.
    assert pick.next_day_open is None
    assert pick.next_day_close is None
    assert pick.next_day_change_pct is None
    assert pick.backtest_at is None

    # Monday's data arrives -> the very same row is now backtestable.
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    assert await ai_pick_service.backtest_ai_picks_open() == 1
    assert await ai_pick_service.backtest_ai_picks_close() == 1

    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_open == 11.0
    assert pick.next_day_close == 11.8
    assert pick.price_at_pick == 10.5


async def test_suspended_stock_stays_pending(db_factory) -> None:
    """If the stock has data for the pick day but none after it, the pick stays pending."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, "000001", MONDAY, open_p=5.0, close_p=5.2)  # other stock only
    pick_id = await _add_pick(db_factory, FRIDAY)

    assert await ai_pick_service.backtest_ai_picks_open() == 0
    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_open is None
    assert pick.next_day_close is None


async def test_price_at_pick_falls_back_to_latest_earlier_close(db_factory) -> None:
    """If the pick date itself has no row, use the nearest earlier close (never 0)."""
    await _add_daily(db_factory, CODE, date(2026, 9, 24), open_p=9.5, close_p=9.8)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    pick_id = await _add_pick(db_factory, FRIDAY)  # Friday itself missing (suspension)

    assert await ai_pick_service.backtest_ai_picks_open() == 1
    pick = await _get_pick(db_factory, pick_id)
    assert pick.price_at_pick == 9.8
    assert pick.next_day_open == 11.0


# ----------------------------------------------------------------------
# (c) Idempotency
# ----------------------------------------------------------------------

async def test_repeated_runs_are_idempotent(db_factory) -> None:
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    await _add_daily(db_factory, CODE, TUESDAY, open_p=12.0, close_p=12.1)
    pick_id = await _add_pick(db_factory, FRIDAY)

    assert await ai_pick_service.backtest_ai_picks_open() == 1
    assert await ai_pick_service.backtest_ai_picks_close() == 1

    first = await _get_pick(db_factory, pick_id)
    snapshot = (
        first.next_day_open,
        first.next_day_close,
        first.next_day_change_pct,
        first.price_at_pick,
    )

    # Second and third runs must be no-ops, not double counting.
    assert await ai_pick_service.backtest_ai_picks_open() == 0
    assert await ai_pick_service.backtest_ai_picks_close() == 0
    assert await ai_pick_service.backtest_ai_picks_open() == 0
    assert await ai_pick_service.backtest_ai_picks_close() == 0

    again = await _get_pick(db_factory, pick_id)
    assert (
        again.next_day_open,
        again.next_day_close,
        again.next_day_change_pct,
        again.price_at_pick,
    ) == snapshot
    # Tuesday's data (12.0) must never leak into the Friday pick's backtest.
    assert again.next_day_open == 11.0
    assert again.next_day_change_pct == pytest.approx(round((11.8 - 11.0) / 11.0 * 100, 2))


async def test_repeated_open_then_close_across_jobs(db_factory) -> None:
    """Running close -> open -> close -> open repeatedly converges and stays stable."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    pick_id = await _add_pick(db_factory, FRIDAY)

    for _ in range(3):
        await ai_pick_service.backtest_ai_picks_close()
        await ai_pick_service.backtest_ai_picks_open()

    pick = await _get_pick(db_factory, pick_id)
    assert pick.next_day_open == 11.0
    assert pick.next_day_close == 11.8
    assert pick.price_at_pick == 10.5
    assert pick.next_day_change_pct == pytest.approx(round((11.8 - 11.0) / 11.0 * 100, 2))


async def test_multiple_picks_are_all_handled(db_factory) -> None:
    """Mixed set: one backtestable, one not yet — counts and state are exact."""
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    await _add_daily(db_factory, CODE, MONDAY, open_p=11.0, close_p=11.8)
    await _add_daily(db_factory, "000001", TUESDAY, open_p=5.0, close_p=5.2)

    ready_id = await _add_pick(db_factory, FRIDAY, code=CODE)
    later_id = await _add_pick(db_factory, TUESDAY, code="000001")

    assert await ai_pick_service.backtest_ai_picks_open() == 1
    assert await ai_pick_service.backtest_ai_picks_close() == 1

    ready = await _get_pick(db_factory, ready_id)
    later = await _get_pick(db_factory, later_id)
    assert ready.next_day_open == 11.0
    assert ready.next_day_close == 11.8
    assert later.next_day_open is None
    assert later.next_day_close is None

    # Adding the missing day makes the second pick backtestable on the next run.
    await _add_daily(db_factory, "000001", date(2026, 9, 30), open_p=5.3, close_p=5.4)
    assert await ai_pick_service.backtest_ai_picks_open() == 1
    assert await ai_pick_service.backtest_ai_picks_close() == 1
    later = await _get_pick(db_factory, later_id)
    assert later.next_day_open == 5.3
    assert later.next_day_close == 5.4


async def test_no_pending_picks_returns_zero(db_factory) -> None:
    await _add_daily(db_factory, CODE, FRIDAY, open_p=10.0, close_p=10.5)
    assert await ai_pick_service.backtest_ai_picks_open() == 0
    assert await ai_pick_service.backtest_ai_picks_close() == 0
