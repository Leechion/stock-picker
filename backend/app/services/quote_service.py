"""Realtime quote service — whole-market snapshots from the Tencent batch API.

Why batch
---------
The upstream endpoint accepts comma-separated codes and returns one line per
code. Measured on this dataset:

    batch size   result
    ----------   ------------------------------------------
    <= 900       full response
      950        truncated to 1 line (silent failure!)

    3207 codes   the whole market in 7 requests, ~1.1 s, 0 errors over 70
                 back-to-back full refreshes

The 950-code cliff is silent — you get HTTP 200 and one quote — so requests are
capped at :data:`BATCH_SIZE` (500, comfortably clear of it) and every response
is length-checked.

Where quotes live
-----------------
Redis only, never SQLite. A 3-second cadence writing 3207 rows would serialise
against the single SQLite writer and starve the API. Redis keys carry a short
TTL so a stalled poller degrades to "stale" rather than "wrong forever".

Daily OHLCV *is* persisted, but on a much slower cadence — see
``app/services/daily_archiver.py``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

import httpx
from loguru import logger

from app.core.redis import get_redis

QUOTE_URL = "http://qt.gtimg.cn/q="

#: Codes per upstream request. Hard-capped below the observed 950 truncation.
BATCH_SIZE = 500
#: Concurrency across batches. 7 batches in flight keeps a full refresh ~1s.
MAX_CONCURRENCY = 4
#: TTL for a cached quote. Must exceed the poll interval (3s) with margin, so a
#: transient poller failure doesn't instantly blank the UI.
QUOTE_TTL = 30
#: Redis key namespace.
KEY_PREFIX = "rt:quote:"
#: Index of the most recently published snapshot.
SNAPSHOT_KEY = "rt:snapshot"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "http://gu.qq.com/",
}


@dataclass(slots=True)
class Quote:
    """One stock's realtime snapshot.

    Field indices are taken from the upstream's ``~``-delimited payload; only
    the ones this project actually uses are parsed.
    """

    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float          # 手
    amount: float          # 万元
    change_pct: float
    turnover_rate: float | None
    pe: float | None
    pb: float | None
    ts: str                # upstream quote timestamp (yyyyMMddHHMMSS)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _prefixed(code: str) -> str:
    """Tencent expects a market prefix: sh for 5/6/9, otherwise sz."""
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


def _f(fields: list[str], idx: int) -> float | None:
    """Parse a float field, tolerating blanks and malformed values."""
    if idx >= len(fields):
        return None
    raw = fields[idx].strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_quote_line(line: str) -> Quote | None:
    """Parse one ``v_sh600519="..."`` line. Returns None if unusable."""
    if "=" not in line:
        return None
    _, _, payload = line.partition("=")
    payload = payload.strip().strip('"').strip(";")
    if not payload:
        return None
    f = payload.split("~")
    # Need at least through the change fields.
    if len(f) < 33:
        return None

    code = f[2].strip()
    price = _f(f, 3)
    if not code or price is None or price <= 0:
        return None

    return Quote(
        code=code,
        name=f[1].strip(),
        price=price,
        prev_close=_f(f, 4) or 0.0,
        open=_f(f, 5) or 0.0,
        high=_f(f, 33) or 0.0,
        low=_f(f, 34) or 0.0,
        volume=_f(f, 6) or 0.0,
        amount=_f(f, 37) or 0.0,
        change_pct=_f(f, 32) or 0.0,
        turnover_rate=_f(f, 38),
        pe=_f(f, 39),
        pb=_f(f, 46),
        ts=f[30].strip() if len(f) > 30 else "",
    )


def parse_quotes(text: str) -> dict[str, Quote]:
    """Parse a whole batch response into ``{code: Quote}``."""
    out: dict[str, Quote] = {}
    for line in text.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        q = parse_quote_line(line)
        if q is not None:
            out[q.code] = q
    return out


async def _fetch_batch(client: httpx.AsyncClient, codes: list[str]) -> dict[str, Quote]:
    """Fetch one batch, returning {} on any failure.

    The code list is passed via ``params`` rather than string-concatenated into
    the URL: a raw "sh600519,sz000001" path segment makes httpx try to parse
    "600519,sz000001" as a port and raise ``InvalidURL``. Passing params lets
    httpx encode it correctly (the commas are preserved, which the upstream
    requires).

    A short batch is logged loudly: that is the signature of the upstream
    silently truncating an over-long request.
    """
    joined = ",".join(_prefixed(c) for c in codes)
    try:
        resp = await client.get(QUOTE_URL, params={"q": joined})
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Quote batch failed ({len(codes)} codes): {exc}")
        return {}

    quotes = parse_quotes(resp.content.decode("gbk", errors="replace"))
    if not quotes:
        # Retry once with a hand-built URL: some httpx versions percent-encode
        # the commas, which the upstream rejects with an empty body.
        try:
            resp = await client.get(f"{QUOTE_URL}{joined}")
            resp.raise_for_status()
            quotes = parse_quotes(resp.content.decode("gbk", errors="replace"))
        except Exception as exc:
            logger.warning(f"Quote batch retry failed ({len(codes)} codes): {exc}")
            return {}

    if len(quotes) < len(codes):
        logger.warning(
            f"Quote batch short: asked {len(codes)}, got {len(quotes)} "
            f"(upstream truncation?)"
        )
    return quotes


async def fetch_quotes(codes: Iterable[str]) -> dict[str, Quote]:
    """Fetch realtime quotes for `codes`, batched and concurrent."""
    codes = list(codes)
    if not codes:
        return {}

    batches = [codes[i : i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    out: dict[str, Quote] = {}

    async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:

        async def run(batch: list[str]) -> dict[str, Quote]:
            async with sem:
                return await _fetch_batch(client, batch)

        for result in await asyncio.gather(*(run(b) for b in batches)):
            out.update(result)

    return out


# ----------------------------------------------------------------------
# Redis cache
# ----------------------------------------------------------------------

def _entry(q: Quote) -> str:
    return json.dumps(q.to_dict(), ensure_ascii=False)


async def store_quotes(quotes: dict[str, Quote]) -> int:
    """Write quotes to Redis with a TTL. Returns the number stored.

    Uses a pipeline so 3200 writes cost one round trip. Redis being down is
    non-fatal: the caller still gets the fresh data in memory.
    """
    if not quotes:
        return 0
    try:
        r = await get_redis()
        pipe = r.pipeline()
        for code, q in quotes.items():
            pipe.set(f"{KEY_PREFIX}{code}", _entry(q), ex=QUOTE_TTL)
        pipe.set(
            SNAPSHOT_KEY,
            json.dumps(
                {"count": len(quotes), "at": datetime.now().isoformat()},
                ensure_ascii=False,
            ),
            ex=QUOTE_TTL,
        )
        await pipe.execute()
        return len(quotes)
    except Exception as exc:
        logger.warning(f"Failed to cache {len(quotes)} quotes in Redis: {exc}")
        return 0


async def get_cached_quotes(codes: Iterable[str]) -> dict[str, Quote]:
    """Read cached quotes. Codes with no live entry are simply absent."""
    codes = list(codes)
    if not codes:
        return {}
    try:
        r = await get_redis()
        raw = await r.mget([f"{KEY_PREFIX}{c}" for c in codes])
    except Exception as exc:
        logger.warning(f"Failed to read quote cache: {exc}")
        return {}

    out: dict[str, Quote] = {}
    for code, blob in zip(codes, raw):
        if not blob:
            continue
        try:
            out[code] = Quote(**json.loads(blob))
        except (ValueError, TypeError):
            continue
    return out


async def get_snapshot_meta() -> dict[str, Any] | None:
    """When the last full-market snapshot was published, and how big it was."""
    try:
        r = await get_redis()
        raw = await r.get(SNAPSHOT_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None
