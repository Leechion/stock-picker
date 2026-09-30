"""Regression tests for sync cancellation semantics and silent data-layer failures.

Covered defects:
  #1  `sync_all_stocks` fell through after `break` on cancellation, committing
      everything, broadcasting "complete" and logging "Sync complete".
  #6a `_redis_get` / `_redis_set` swallowed every exception with a bare `pass`.

All tests run fully offline: the provider layer and Redis are faked.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.models.stock import StockDaily, StockInfo
from app.services import data_service
from app.services.data_service import (
    _redis_get,
    _redis_set,
    sync_all_stocks,
)

# > BATCH_SIZE (50) in sync_all_stocks, so cancellation can hit between batches.
TOTAL_STOCKS = 60
BATCH_SIZE = 50


def make_stock_list(count: int = TOTAL_STOCKS) -> pd.DataFrame:
    """Main-board stock list, matching the columns the sync loop reads."""
    codes = [f"{600000 + i:06d}" for i in range(count)]
    return pd.DataFrame({"代码": codes, "名称": [f"股票{i}" for i in range(count)]})


def make_daily_df(days: int = 3) -> pd.DataFrame:
    """Minimal eastmoney-style daily frame in Chinese columns."""
    today = date.today()
    dates = [today - timedelta(days=days - 1 - i) for i in range(days)]
    return pd.DataFrame(
        {
            "日期": dates,
            "开盘": [10.0] * days,
            "收盘": [10.5] * days,
            "最高": [10.8] * days,
            "最低": [9.9] * days,
            "成交量": [1_000_000.0] * days,
            "成交额": [10_000_000.0] * days,
        }
    )


@pytest.fixture
def recorded_broadcasts(monkeypatch):
    """Capture every (done, total, status) progress broadcast."""
    calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        data_service,
        "_broadcast_sync_progress",
        lambda done, total, status: calls.append((done, total, status)),
    )
    return calls


@pytest.fixture
def offline_providers(monkeypatch):
    """Fake the provider layer: stock list + per-code daily data, no network."""
    fetched: list[str] = []

    async def fake_stock_list() -> pd.DataFrame:
        return make_stock_list()

    async def fake_daily_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fetched.append(code)
        return make_daily_df()

    monkeypatch.setattr(data_service.provider_manager, "async_fetch_stock_list", fake_stock_list)
    monkeypatch.setattr(data_service, "fetch_daily_data", fake_daily_data)
    return fetched


@pytest.fixture(autouse=True)
def clean_events():
    """Keep the module-level cancellation flags from leaking between tests."""
    data_service.sync_cancel_event.clear()
    data_service.shutdown_event.clear()
    yield
    data_service.sync_cancel_event.clear()
    data_service.shutdown_event.clear()


def statuses(calls) -> list[str]:
    return [status for _, _, status in calls]


@pytest.mark.asyncio
async def test_sync_completes_normally_when_not_cancelled(session, recorded_broadcasts, offline_providers):
    """Regression for the `cancelled` NameError: the happy path must not raise."""
    count = await sync_all_stocks(session, days_back=80, include_history=True)

    assert count == TOTAL_STOCKS
    assert "complete" in statuses(recorded_broadcasts)
    assert "cancelled" not in statuses(recorded_broadcasts)
    # Terminal broadcast must report full progress.
    assert recorded_broadcasts[-1] == (TOTAL_STOCKS, TOTAL_STOCKS, "complete")

    stocks = (await session.execute(StockInfo.__table__.select())).all()
    daily = (await session.execute(StockDaily.__table__.select())).all()
    assert len(stocks) == TOTAL_STOCKS
    assert len(daily) == TOTAL_STOCKS * 3


@pytest.mark.asyncio
async def test_cancel_before_first_batch_commits_nothing_and_reports_cancelled(
    session, recorded_broadcasts, offline_providers, monkeypatch
):
    """Cancellation before the first batch: no fetch, no "complete" broadcast."""
    data_service.sync_cancel_event.set()

    count = await sync_all_stocks(session, days_back=80, include_history=True)

    assert count == 0
    assert offline_providers == []
    assert "complete" not in statuses(recorded_broadcasts)
    assert "saving" not in statuses(recorded_broadcasts)
    assert recorded_broadcasts[-1][2] == "cancelled"
    # Progress must stay at the cancellation point, never jump to len(candidates).
    assert recorded_broadcasts[-1][0] < TOTAL_STOCKS
    assert (await session.execute(StockDaily.__table__.select())).all() == []


@pytest.mark.asyncio
async def test_cancel_midway_commits_partial_data_and_never_broadcasts_complete(
    session, recorded_broadcasts, offline_providers, monkeypatch
):
    """Cancel after the first batch: only that batch is persisted."""
    real_gather = data_service.asyncio.gather
    calls = {"n": 0}

    async def cancelling_gather(*aws, **kwargs):
        results = await real_gather(*aws, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the user hitting /stocks/sync-cancel during batch 1.
            data_service.sync_cancel_event.set()
        return results

    monkeypatch.setattr(data_service.asyncio, "gather", cancelling_gather)

    count = await sync_all_stocks(session, days_back=80, include_history=True)

    # Exactly one batch of BATCH_SIZE stocks was fetched and committed.
    assert count == BATCH_SIZE
    assert len(offline_providers) == BATCH_SIZE
    assert calls["n"] == 1

    assert "complete" not in statuses(recorded_broadcasts)
    assert "cancelled" in statuses(recorded_broadcasts)
    terminal_done, terminal_total, terminal_status = recorded_broadcasts[-1]
    assert terminal_status == "cancelled"
    assert terminal_total == TOTAL_STOCKS
    assert terminal_done <= BATCH_SIZE < TOTAL_STOCKS  # partial, never 100%

    stocks = (await session.execute(StockInfo.__table__.select())).all()
    daily = (await session.execute(StockDaily.__table__.select())).all()
    assert len(stocks) == BATCH_SIZE
    assert len(daily) == BATCH_SIZE * 3


@pytest.mark.asyncio
async def test_shutdown_event_also_takes_the_cancelled_path(session, recorded_broadcasts, offline_providers):
    """Server shutdown must reuse the cancellation path, not report success."""
    data_service.shutdown_event.set()

    count = await sync_all_stocks(session, days_back=80, include_history=True)

    assert count == 0
    assert "complete" not in statuses(recorded_broadcasts)
    assert recorded_broadcasts[-1][2] == "cancelled"


@pytest.mark.asyncio
async def test_redis_helpers_log_instead_of_silently_swallowing(monkeypatch):
    """#6a: Redis outages must not raise, but must be logged (not silently passed)."""

    async def boom():
        raise ConnectionError("redis is down")

    monkeypatch.setattr("app.core.redis.get_redis", boom)

    messages: list[str] = []

    def capture(message):
        messages.append(message)

    monkeypatch.setattr(data_service.logger, "debug", capture)

    assert await _redis_get("sync:test:600000") is None
    await _redis_set("sync:test:600000", {"code": "600000"})

    assert len(messages) == 2, f"expected both Redis failures logged, got {messages}"
    assert any("sync:test:600000" in m for m in messages)
    assert all("Redis" in m for m in messages)
