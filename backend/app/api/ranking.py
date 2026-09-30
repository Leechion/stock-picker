"""Ranking API routes.

Endpoints:
  GET /api/rankings/            - List ranks with pagination (date, page, page_size)
  GET /api/rankings/:code       - Single stock rank (requires ?date=)
  POST /api/rankings/compute    - Compute rankings for all stocks
  GET /api/sync/status          - Get sync status
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cache, cached
from app.models.stock import StockRanking

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


# NOTE: deliberately NOT decorated with @cached(ttl=300).
# 1) The cache key was built from the request path/params but did not include
#    `strategy`, so requests for different strategies collided and returned each
#    other's data. Caching here is a correctness hazard while the key is
#    incomplete.
# 2) Adding the `search` parameter makes the key space essentially unbounded
#    (arbitrary user-typed substrings), so a TTL cache would be pure churn.
# 3) Ranking rows change once per trading day (and on every /rankings/compute),
#    so a 300s TTL buys almost nothing for the correctness risk it adds.
# Do not re-add the decorator without extending the key to cover every filter
# parameter (date, strategy, search, page, page_size).
@router.get("/rankings/")
async def get_rankings(
    trading_date: date = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    strategy: str = Query(default=None),
    search: str = Query(default=None, description="搜索股票代码或名称"),
    session: AsyncSession = Depends(get_db),
):
    target_date = trading_date or date.today()

    from app.services.ranking_service import get_ranking_list
    records, total = await get_ranking_list(session, target_date, page, page_size, strategy=strategy, search=search)

    return _ok({
        "items": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    })


@router.get("/rankings/history/{code}")
async def get_ranking_history_endpoint(
    code: str,
    days: int = Query(default=30, ge=7, le=365),
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    from app.services.ranking_service import get_ranking_history
    history = await get_ranking_history(session, code, days, strategy)
    return _ok(history)


@router.get("/rankings/peers/{code}")
async def get_peer_stocks_endpoint(
    code: str,
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    from app.services.ranking_service import get_peer_stocks
    peers = await get_peer_stocks(session, code, strategy)
    return _ok(peers)


@router.get("/rankings/{code}")
async def get_stock_rank_endpoint(
    code: str,
    trading_date: date = Query(default=None),
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    target_date = trading_date or date.today()

    from app.services.ranking_service import get_stock_rank
    record = await get_stock_rank(session, code, target_date, strategy=strategy)

    if record is None:
        return _err(f"Ranking not found for {code} on {target_date}", 404)

    return _ok(record)


@router.post("/rankings/compute")
async def compute_ranking(
    trading_date: date = Query(default=None),
    concurrency: int = Query(default=12, ge=1, le=32),
):
    """Launch the full factor → ranking → alert pipeline as a background job.

    This endpoint deliberately does **not** run the pipeline inline. It used to,
    which meant a ~16 minute computation held the HTTP connection open, blocked
    the frontend's 30s axios timeout, reported no progress, and could not be
    cancelled. The pipeline was also duplicated here and in the scheduler.

    It now returns a ``job_id`` immediately. Track it with:

    * ``GET  /api/jobs/{job_id}``         — poll status and progress
    * ``POST /api/jobs/{job_id}/cancel``  — cooperative cancellation
    * WebSocket channel ``job_progress``  — live push
    """
    from app.core.jobs import launch

    target = trading_date or date.today()

    async def _run(ctx):
        from app.pipelines import run_full_ranking_pipeline

        return await run_full_ranking_pipeline(
            ctx, trading_date=target, concurrency=concurrency
        )

    job_id = await launch(
        "full_ranking",
        _run,
        {"trading_date": str(target), "concurrency": concurrency},
    )
    return _ok(
        {
            "job_id": job_id,
            "job_type": "full_ranking",
            "status": "pending",
            "trading_date": str(target),
            "concurrency": concurrency,
            "poll_url": f"/api/jobs/{job_id}",
        },
        "任务已启动",
    )


@router.post("/notifications/test")
async def test_notification():
    """Send a test notification with today's rankings (includes AI report)."""
    from app.services.notification_service import send_daily_notification

    sent = await send_daily_notification()
    if sent:
        return _ok({"sent": True}, "Notification sent successfully")
    return _err("Failed to send notification (check WECHAT_WEBHOOK_URL config)", 500)


@router.get("/notifications/preview")
async def preview_notification(
    trading_date: date = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    """Preview the full notification message without sending."""
    from app.services.ai_report_service import generate_report
    from app.services.notification_service import (
        format_ranking_message, format_index_section,
        format_alert_section, fetch_market_indices, fetch_price_alerts,
    )
    from app.services.ranking_service import get_ranking_list
    from app.core.config import settings

    target_date = trading_date or date.today()
    records, _ = await get_ranking_list(
        session, target_date, page=1, page_size=settings.notification_top_n
    )
    if not records:
        return _err(f"No rankings for {target_date}", 404)

    indices = fetch_market_indices()
    alerts = await fetch_price_alerts(target_date)
    ai_text = generate_report(records)

    sections = []
    idx_sec = format_index_section(indices)
    if idx_sec:
        sections.append(idx_sec)
    alt_sec = format_alert_section(alerts)
    if alt_sec:
        sections.append(alt_sec)
    sections.append(format_ranking_message(records, target_date, ai_text))

    message = "\n".join(sections)
    return _ok({"message": message, "ai_text": ai_text})
