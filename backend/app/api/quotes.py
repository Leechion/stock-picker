"""Realtime quote API.

    GET /api/quotes/            - quotes for specific codes, or cached snapshot
    GET /api/quotes/market      - market breadth summary + poller health

Clients normally load a first paint from ``/quotes/`` and then receive deltas
over the ``quotes`` WebSocket channel, so they never need a manual refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.market_calendar import is_trading_session, now_cn, session_label
from app.services import quote_poller
from app.services.quote_service import get_cached_quotes, get_snapshot_meta

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


@router.get("/quotes/")
async def get_quotes(
    codes: str = Query(
        default="",
        description="逗号分隔的股票代码，例如 600519,000001。留空则返回缓存快照概览。",
    ),
    limit: int = Query(default=200, ge=1, le=5000),
):
    """Quotes for the requested codes, served from the poller's cache.

    Never blocks on the upstream: if the poller is running the data is at most
    ``POLL_INTERVAL`` old, and if it is stopped the cache simply ages out.
    """
    code_list = [c.strip() for c in codes.split(",") if c.strip()]

    if not code_list:
        snap = quote_poller.get_latest()
        meta = await get_snapshot_meta()
        return _ok(
            {
                "count": len(snap),
                "snapshot": meta,
                "session": session_label(),
            }
        )

    code_list = code_list[:5000]

    # Prefer the in-memory snapshot (freshest), fall back to Redis.
    live = quote_poller.get_latest()
    items = []
    missing = []
    for code in code_list:
        q = live.get(code)
        if q is not None:
            items.append(q.to_dict())
        else:
            missing.append(code)

    if missing:
        cached = await get_cached_quotes(missing)
        items.extend(q.to_dict() for q in cached.values())

    return _ok(
        {
            "items": items,
            "requested": len(code_list),
            "returned": len(items),
            "session": session_label(),
        }
    )


@router.get("/quotes/market")
async def market_overview():
    """Market breadth plus poller health — useful as a UI header and for ops."""
    snap = quote_poller.get_latest()
    rising = sum(1 for q in snap.values() if q.change_pct > 0)
    falling = sum(1 for q in snap.values() if q.change_pct < 0)
    flat = len(snap) - rising - falling

    return _ok(
        {
            "session": session_label(),
            "is_trading": is_trading_session(),
            "time": now_cn().isoformat(),
            "breadth": {
                "total": len(snap),
                "rising": rising,
                "falling": falling,
                "flat": flat,
            },
            "poller": {
                **quote_poller.get_stats(),
                "running": quote_poller.is_running(),
            },
            "snapshot": await get_snapshot_meta(),
        }
    )
