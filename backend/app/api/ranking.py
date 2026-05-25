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


@router.get("/rankings/")
@cached(ttl=300, prefix="ranking_list")
async def get_rankings(
    trading_date: date = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    strategy: str = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    target_date = trading_date or date.today()

    from app.services.ranking_service import get_ranking_list
    records, total = await get_ranking_list(session, target_date, page, page_size, strategy=strategy)

    return _ok({
        "items": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    })


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
    session: AsyncSession = Depends(get_db),
):
    """Run full pipeline: compute factors for all stocks → compute rankings."""
    import asyncio
    from app.services.factor_engine import compute_factors_for_stock
    from app.services.data_service import get_history
    from app.models.stock import StockInfo, FactorValue, StockFundamental
    from sqlalchemy import delete as sql_delete, insert

    result = await session.execute(select(StockInfo.code, StockInfo.industry))
    stocks = result.all()
    if not stocks:
        return _err("No stocks found", 400)

    codes = [row[0] for row in stocks]
    industry_map = {row[0]: row[1] for row in stocks}

    try:
        from app.services.capital_flow import fetch_flow_and_chip
        from app.services.sector_service import fetch_sector_performance, compute_sector_heat
        import pandas as pd

        # Pre-fetch sector heat once
        try:
            sectors = await asyncio.get_running_loop().run_in_executor(None, fetch_sector_performance)
            sector_heat_scores = compute_sector_heat(sectors) if sectors else {}
        except Exception:
            sector_heat_scores = {}

        # Load all fundamentals in one query
        fund_result = await session.execute(select(StockFundamental))
        fund_map = {}
        for fr in fund_result.scalars().all():
            fund_map[fr.code] = {
                "pe_ttm": fr.pe_ttm, "pb": fr.pb, "roe": fr.roe,
                "revenue_growth": fr.revenue_growth, "profit_growth": fr.profit_growth,
                "debt_ratio": fr.debt_ratio,
            }

        # Concurrent factor computation with semaphore
        sem = asyncio.Semaphore(10)
        total = 0
        all_records = []

        async def process_stock(code: str):
            nonlocal total
            async with sem:
                df = await get_history(session, code, days=80)
                if df.empty:
                    return

                loop = asyncio.get_running_loop()
                flow_data = await loop.run_in_executor(None, lambda c=code: fetch_flow_and_chip(c))

                sector_heat = sector_heat_scores.get(industry_map.get(code, ""), None)
                raw_factors = compute_factors_for_stock(
                    df, code, fund_map.get(code), flow_data, sector_heat,
                )
                if raw_factors:
                    now = pd.Timestamp.now()
                    for f in raw_factors:
                        all_records.append({
                            "code": code, "factor_name": f["factor_name"],
                            "factor_type": f["factor_type"], "value": f["value"],
                            "computed_at": now,
                        })
                    total += 1

        await asyncio.gather(*[process_stock(c) for c in codes])

        # Batch delete + insert
        await session.execute(sql_delete(FactorValue))
        for i in range(0, len(all_records), 500):
            await session.execute(insert(FactorValue), all_records[i:i + 500])
        await session.commit()

        target = trading_date or date.today()
        from app.services.ranking_service import compute_all_rankings
        rank_result = await compute_all_rankings(session, target)
        cache.invalidate("ranking_")

        return _ok({
            "total": total,
            "updated_at": str(target),
            "status": "success",
            **rank_result,
        })
    except Exception as e:
        await session.rollback()
        return _err(f"Ranking computation failed: {e}", 500)


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
