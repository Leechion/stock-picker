"""Intraday daily-bar archiver — keeps today's OHLCV row current during the session.

The problem
-----------
``stock_daily`` was written only by the 15:05 sync, so the newest row was
*yesterday* until well after the close. Anything reading today's bar — the
factor pipeline, the screener, the UI — was working with stale data all day.

What this does
--------------
While the market is open, every ``ARCHIVE_INTERVAL`` (5 minutes) it takes the
in-memory realtime snapshot (already maintained by the quote poller, so no
extra upstream calls) and upserts **today's row** for every stock:

    09:35  open=今开  high=盘中最高  low=盘中最低  close=当前价  volume/amount=累计
    14:55  ...same, refreshed
    15:05  final: the poller's last post-close snapshot is the settled bar

The result is that ``stock_daily`` is always current to within 5 minutes during
the session, and the 15:05 sync becomes a confirmation rather than the only
source of truth.

Why not write every 3 seconds
-----------------------------
SQLite serialises writers. 3200 upserts every 3 seconds would contend with the
API's reads and the factor pipeline's bulk insert. Five minutes is frequent
enough for daily-bar semantics (the bar only meaningfully changes once per
session) and cheap enough to be invisible.

Deduplication
-------------
``stock_daily`` has **no unique constraint on (code, trade_date)** — only an
index on ``code``. A naive INSERT would therefore append a new row on every
tick and grow the table without bound. This module deletes today's rows first
and inserts fresh ones inside a single transaction, which is both correct and
fast (one DELETE + one bulk INSERT).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from loguru import logger
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select

from app.core.database import AsyncSessionLocal
from app.core.market_calendar import is_trading_session, now_cn, session_label
from app.models.stock import StockDaily

#: Minutes between archive passes. See module docstring for why not faster.
ARCHIVE_INTERVAL = 300.0
#: Seconds to sleep when the market is closed.
IDLE_INTERVAL = 60.0
#: Rows per INSERT statement.
CHUNK = 500

_stats: dict[str, Any] = {
    "archives": 0,
    "rows": 0,
    "errors": 0,
    "last_at": None,
}


def get_stats() -> dict[str, Any]:
    return dict(_stats)


def _quote_date(q: Any) -> date | None:
    """Parse a quote's own timestamp (``yyyyMMddHHMMSS``) into a date.

    Returns None when the field is missing or malformed.
    """
    ts = getattr(q, "ts", None)
    if not ts or len(ts) < 8 or not ts[:8].isdigit():
        return None
    try:
        return date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
    except ValueError:
        return None


async def archive_once(trade_date: date | None = None) -> int:
    """Upsert today's daily bar for every stock that has a live quote.

    Returns the number of rows written.
    """
    from app.services import quote_poller

    quotes = quote_poller.get_latest()
    if not quotes:
        logger.debug("Intraday archive: no quotes yet, skipping")
        return 0

    now = datetime.now()

    rows: list[dict[str, Any]] = []
    # Date the bar by the QUOTE'S OWN timestamp, not by the wall clock.
    #
    # During a holiday or after midnight the feed still serves the previous
    # session's close. Stamping that with today's date writes a phantom bar for
    # a day the market never traded (observed: a full 3207-row bar written for
    # 2026-10-01, a holiday, carrying 2026-09-30's prices).
    quote_dates: set[date] = set()
    for q in quotes.values():
        d = _quote_date(q)
        if d is not None:
            quote_dates.add(d)

    if trade_date is not None:
        target = trade_date
    elif len(quote_dates) == 1:
        target = next(iter(quote_dates))
    elif quote_dates:
        target = max(quote_dates)
    else:
        # No parseable timestamp: fall back to the exchange-local date.
        target = now_cn().date()

    if target != now_cn().date():
        logger.info(
            f"Intraday archive: quote timestamps say {target} "
            f"(local date is {now_cn().date()}); dating bars accordingly"
        )

    for code, q in quotes.items():
        if not q.price or q.price <= 0:
            continue
        # Skip anything not belonging to the target session, so a stale tick
        # cannot inject a wrong price into today's bar.
        qd = _quote_date(q)
        if qd is not None and qd != target:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": target,
                "open": q.open or q.prev_close or q.price,
                "close": q.price,
                "high": q.high or q.price,
                "low": q.low or q.price,
                # Upstream reports 手 and 万元; the daily table stores the same
                # units the sync path writes, so pass them through unchanged.
                "volume": q.volume or 0.0,
                "amount": q.amount or 0.0,
                "change_pct": q.change_pct,
            }
        )

    if not rows:
        logger.debug("Intraday archive: no usable quotes, skipping")
        return 0

    try:
        async with AsyncSessionLocal() as session:
            # Replace rather than append: there is no unique constraint to
            # conflict on, so an INSERT-only path would duplicate every tick.
            await session.execute(
                sql_delete(StockDaily).where(StockDaily.trade_date == target)
            )
            for i in range(0, len(rows), CHUNK):
                await session.execute(insert(StockDaily), rows[i : i + CHUNK])
            await session.commit()
    except Exception as exc:
        _stats["errors"] += 1
        logger.warning(f"Intraday archive failed: {exc}")
        return 0

    _stats["archives"] += 1
    _stats["rows"] = len(rows)
    _stats["last_at"] = now.isoformat()
    logger.info(
        f"Intraday archive: wrote {len(rows)} bars for {target} "
        f"({session_label()})"
    )
    return len(rows)


async def _loop() -> None:
    logger.info("Intraday daily-bar archiver started")
    while True:
        try:
            if not is_trading_session():
                await _sleep(IDLE_INTERVAL)
                continue
            await archive_once()
            await _sleep(ARCHIVE_INTERVAL)
        except Exception as exc:
            _stats["errors"] += 1
            logger.warning(f"Intraday archiver error (will retry): {exc}")
            await _sleep(60.0)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


_task = None


def start_archiver() -> None:
    import asyncio

    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="intraday-archiver")


async def stop_archiver() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except Exception:
            pass
        _task = None


def is_running() -> bool:
    return _task is not None and not _task.done()


async def today_bar_state() -> dict[str, Any]:
    """Diagnostics: how many stocks have a bar for today."""
    target = now_cn().date()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(StockDaily.code).where(StockDaily.trade_date == target)
            )
        ).scalars().all()
    return {
        "trade_date": str(target),
        "stocks_with_today_bar": len(rows),
        "session": session_label(),
        **get_stats(),
    }
