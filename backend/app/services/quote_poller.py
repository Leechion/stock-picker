"""Realtime quote poller — keeps the whole market fresh in Redis.

Runs as a single background asyncio task for the process lifetime:

    every POLL_INTERVAL (3s) while the market is open:
        7 batched requests -> 3207 quotes (~0.4-1.1s)
        -> Redis (30s TTL)
        -> WebSocket "quotes" push (compact payload)

Design notes
------------
* **Outside market hours it idles.** A quote API returning yesterday's close
  every 3 seconds is pure waste; the loop sleeps and re-checks the calendar.
  The last snapshot stays in Redis until its TTL lapses.
* **Never raises.** A failing poll logs and waits for the next tick — the
  poller is infrastructure and must not die on a transient network error.
* **Pushes deltas, not the world.** Sending 3207 quotes over the socket every
  3 seconds is ~400 KB per tick per client. Only codes whose price actually
  moved are pushed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from app.core.market_calendar import now_cn, should_poll_quotes
from app.services.quote_service import Quote, fetch_quotes, store_quotes

#: Seconds between full-market refreshes while open.
POLL_INTERVAL = 3.0
#: Seconds to wait when the market is closed.
IDLE_INTERVAL = 30.0

_task: asyncio.Task | None = None
#: Last observed price per code, used to compute what actually changed.
_last_prices: dict[str, float] = {}
#: Most recent snapshot, in memory, for instant REST responses.
_latest: dict[str, Quote] = {}
_stats: dict[str, Any] = {"ticks": 0, "errors": 0, "last_at": None, "last_count": 0}


def get_latest() -> dict[str, Quote]:
    """In-memory snapshot — always fresher than Redis, and free to read."""
    return _latest


def get_stats() -> dict[str, Any]:
    return dict(_stats)


async def _load_universe() -> list[str]:
    """All stock codes to poll. Re-read periodically so new listings appear."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.stock import StockInfo

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(StockInfo.code))).scalars().all()
    return list(rows)


async def refresh_once() -> dict[str, Quote]:
    """Fetch, cache, and publish one full-market snapshot."""
    codes = await _load_universe()
    if not codes:
        logger.warning("Quote poller: empty universe, skipping tick")
        return {}

    quotes = await fetch_quotes(codes)
    if not quotes:
        _stats["errors"] += 1
        return {}

    global _latest
    _latest = quotes
    await store_quotes(quotes)

    _stats["ticks"] += 1
    _stats["last_at"] = datetime.now().isoformat()
    _stats["last_count"] = len(quotes)

    await _publish_changes(quotes)
    return quotes


async def _publish_changes(quotes: dict[str, Quote]) -> None:
    """Push only the codes whose price moved since the previous tick."""
    changed: list[dict[str, Any]] = []
    for code, q in quotes.items():
        prev = _last_prices.get(code)
        if prev is None or prev != q.price:
            changed.append(
                {
                    "code": code,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "high": q.high,
                    "low": q.low,
                    "volume": q.volume,
                    "amount": q.amount,
                }
            )
        _last_prices[code] = q.price

    if not changed:
        return

    try:
        from app.core.websocket import monitor_hub

        await monitor_hub.broadcast(
            "quotes",
            {"count": len(changed), "total": len(quotes), "items": changed},
        )
    except Exception as exc:
        logger.debug(f"Quote push failed (non-fatal): {exc}")


async def _loop() -> None:
    logger.info("Realtime quote poller started")
    universe_refresh_at = 0.0
    while True:
        try:
            loop_time = asyncio.get_running_loop().time()

            if not should_poll_quotes():
                # Market closed: stop burning requests.
                if _stats["ticks"] % 60 == 1:
                    logger.debug("Quote poller idle (market closed)")
                await asyncio.sleep(IDLE_INTERVAL)
                continue

            await refresh_once()
            universe_refresh_at = loop_time
            await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Realtime quote poller stopping")
            break
        except Exception as exc:
            _stats["errors"] += 1
            logger.warning(f"Quote poller error (will retry): {exc}")
            await asyncio.sleep(POLL_INTERVAL)


def start_poller() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="quote-poller")


async def stop_poller() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None


def is_running() -> bool:
    return _task is not None and not _task.done()
