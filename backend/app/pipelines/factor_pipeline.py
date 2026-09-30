"""Factor computation pipeline — the ONE place factors are computed.

Before this module the same four-step pipeline existed twice, with different
bug fixes applied to each copy:

* ``app/api/ranking.py::compute_ranking``  (semaphore 10, SHARED session → crashed)
* ``app/core/scheduler.py::run_daily_ranking`` (semaphore 20, per-coroutine session)

They drifted, and only one of them was ever fixed. Both now delegate here.

Design rules
------------
* Each worker coroutine opens **its own** ``AsyncSessionLocal()``. An
  ``AsyncSession`` must never be shared across ``asyncio.gather``.
* Phase 1 (compute) is read-only and fully concurrent.
* Phase 2 (persist) is a single serial transaction, so a cancel can never leave
  a half-deleted ``factor_values`` table.
* Progress and cancellation are checked per item via ``JobContext``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select

from app.core.database import AsyncSessionLocal
from app.core.jobs import JobCancelled, JobContext
from app.models.stock import FactorValue, StockFundamental, StockInfo

#: Concurrent factor computations. Each holds its own DB session.
DEFAULT_CONCURRENCY = 12
#: Rows per bulk INSERT statement.
INSERT_CHUNK = 500
#: Trading days of history fed to the factor engine.
HISTORY_DAYS = 80


async def _load_universe() -> tuple[list[str], dict[str, str | None], dict[str, dict]]:
    """Pre-load the read-only inputs once, before any concurrency starts.

    Returns ``(codes, industry_map, fundamentals_map)``.
    """
    from app.services.ranking_service import get_eligible_codes

    async with AsyncSessionLocal() as session:
        eligible = await get_eligible_codes(session)

        rows = (await session.execute(select(StockInfo.code, StockInfo.industry))).all()
        industry_map = {code: ind for code, ind in rows}

        fund_rows = (await session.execute(select(StockFundamental))).scalars().all()
        fund_map = {
            fr.code: {
                "pe_ttm": fr.pe_ttm,
                "pb": fr.pb,
                "roe": fr.roe,
                "revenue_growth": fr.revenue_growth,
                "profit_growth": fr.profit_growth,
                "debt_ratio": fr.debt_ratio,
            }
            for fr in fund_rows
        }

    codes = sorted(c for c in industry_map if c in eligible)
    return codes, industry_map, fund_map


async def _load_sector_heat() -> dict[str, float]:
    """Best-effort sector heat map; failure degrades to an empty map."""
    try:
        from app.services import sector_service

        loop = asyncio.get_running_loop()
        sectors = await loop.run_in_executor(None, sector_service.fetch_sector_performance)
        if sectors:
            return await loop.run_in_executor(
                None, sector_service.compute_sector_heat, sectors
            )
    except Exception as exc:
        logger.warning(f"Sector heat preload failed, continuing without it: {exc}")
    return {}


async def _compute_one(
    code: str,
    industry_map: dict[str, str | None],
    fund_map: dict[str, dict],
    sector_heat_map: dict[str, float],
    sem: asyncio.Semaphore,
    cancel_event: asyncio.Event | None = None,
) -> list[dict[str, Any]]:
    """Compute raw factors for a single stock using its OWN session."""
    from app.services.capital_flow import fetch_flow_and_chip
    from app.services.data_service import get_history
    from app.services.factor_engine import compute_factors_for_stock

    async with sem:
        # Re-check AFTER acquiring the semaphore. Creating every worker coroutine
        # up front means they all pass an early check before a cancel can arrive;
        # without this second check a cancel signalled at 15% still ran to ~100%
        # (reproduced: all 200 fake workers completed despite a mid-run cancel).
        if cancel_event is not None and cancel_event.is_set():
            raise JobCancelled()

        async with AsyncSessionLocal() as session:
            df = await get_history(session, code, days=HISTORY_DAYS)
        if cancel_event is not None and cancel_event.is_set():
            raise JobCancelled()
        if df is None or df.empty:
            return []

        loop = asyncio.get_running_loop()
        flow_data = await loop.run_in_executor(None, lambda c=code: fetch_flow_and_chip(c))

        sector_heat = sector_heat_map.get(industry_map.get(code) or "")
        raw = compute_factors_for_stock(
            df, code, fund_map.get(code), flow_data, sector_heat
        )
        return raw or []


async def run_factor_pipeline(
    ctx: JobContext,
    *,
    trading_date: date | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, Any]:
    """Compute factors for every eligible stock, then persist them.

    Steps:
      1. Load the eligible universe and preload read-only inputs.
      2. Compute factors concurrently, one session per worker.
      3. Replace ``factor_values`` in a single transaction.
    """
    target = trading_date or date.today()
    ctx.raise_if_cancelled()

    # ---- Step 1: universe -------------------------------------------------
    await ctx.report(0, 0, "加载股票池…")
    codes, industry_map, fund_map = await _load_universe()
    if not codes:
        return {"stocks_computed": 0, "factors_written": 0, "date": str(target)}

    ctx.raise_if_cancelled()
    total = len(codes)
    await ctx.report(0, total, f"待计算 {total} 只股票")

    # ---- Step 2: compute (concurrent, isolated sessions) ------------------
    sector_heat_map = await _load_sector_heat()
    ctx.raise_if_cancelled()

    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    completed = 0
    computed_codes = 0
    progress_lock = asyncio.Lock()
    now = pd.Timestamp.now()
    all_records: list[dict[str, Any]] = []

    async def worker(code: str) -> None:
        nonlocal done, completed, computed_codes
        ctx.raise_if_cancelled()
        try:
            raw = await _compute_one(
                code, industry_map, fund_map, sector_heat_map, sem, ctx._cancel_event
            )
        except JobCancelled:
            raise
        except Exception as exc:
            logger.debug(f"Factor compute failed for {code}: {exc}")
            raw = []

        async with progress_lock:
            done += 1
            if raw:
                for f in raw:
                    all_records.append(
                        {
                            "code": code,
                            "factor_name": f["factor_name"],
                            "factor_type": f["factor_type"],
                            "value": f["value"],
                            "computed_at": now,
                        }
                    )
                computed_codes += 1
            # Report every 25 items to limit DB writes and WS traffic.
            if done % 25 == 0 or done == total:
                await ctx.report(done, total, f"计算因子 {done}/{total}")

    # `return_exceptions=True` so that ALL workers are awaited to completion
    # before we decide what happened. With the default, the first JobCancelled
    # would propagate while ~3000 sibling tasks were still running detached,
    # leaking sessions and continuing to burn CPU after "cancelled".
    results = await asyncio.gather(
        *(worker(c) for c in codes), return_exceptions=True
    )
    cancelled_midway = any(isinstance(r, JobCancelled) for r in results)
    if cancelled_midway:
        raise JobCancelled()

    # ---- Step 3: persist (serial, atomic) ---------------------------------
    # Nothing has been written yet: if we were cancelled above, the existing
    # factor_values table is still intact rather than half-deleted.
    await ctx.report(done, total, "写入数据库…")

    if all_records:
        async with AsyncSessionLocal() as session:
            await session.execute(sql_delete(FactorValue))
            for i in range(0, len(all_records), INSERT_CHUNK):
                await session.execute(insert(FactorValue), all_records[i : i + INSERT_CHUNK])
            await session.commit()
    else:
        logger.warning("No factor records computed, skipping delete/insert")

    logger.info(
        f"Job {ctx.job_id}: factors computed for {computed_codes}/{total} stocks, "
        f"{len(all_records)} rows"
    )
    return {
        "date": str(target),
        "stocks_total": total,
        "stocks_computed": computed_codes,
        "factors_written": len(all_records),
    }


async def run_ranking_pipeline(
    ctx: JobContext,
    *,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Compute rankings for all strategies from stored factor values.

    ``compute_rankings`` mutates the shared ``strategy_loader`` active name while
    it runs, so strategies are computed **sequentially** (never gathered).
    """
    target = trading_date or date.today()
    ctx.raise_if_cancelled()

    from app.services.ranking_service import compute_rankings, strategy_loader

    strategies = strategy_loader.list_strategies()
    total = len(strategies)
    results: dict[str, Any] = {}
    stocks_computed = 0

    for i, s in enumerate(strategies, start=1):
        ctx.raise_if_cancelled()
        slug = s["slug"]
        await ctx.report(i - 1, total, f"计算策略 {slug}")

        async with AsyncSessionLocal() as session:
            result = await compute_rankings(session, target, strategy_name=slug)

        results[slug] = {
            "status": result.get("status"),
            "stocks_computed": result.get("stocks_computed", 0),
        }
        stocks_computed = max(stocks_computed, result.get("stocks_computed", 0))

    await ctx.report(total, total, "排名完成")
    logger.info(f"Job {ctx.job_id}: rankings computed for {stocks_computed} stocks on {target}")
    return {
        "date": str(target),
        "stocks_computed": stocks_computed,
        "strategies": results,
    }
