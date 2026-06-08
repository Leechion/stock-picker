"""AI picks API routes."""
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.ai_pick import AIPick

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/ai-picks/today")
async def get_today_picks():
    """Get today's AI picks. Returns empty list if no picks yet."""
    async with AsyncSessionLocal() as session:
        stmt = select(func.max(AIPick.pick_date))
        latest = (await session.execute(stmt)).scalar_one_or_none()

        if not latest:
            return _ok({
                "picks": [],
                "pick_date": str(date.today()),
                "confidence": None,
            })

        stmt = (
            select(AIPick)
            .where(AIPick.pick_date == latest)
            .order_by(AIPick.id)
        )
        result = await session.execute(stmt)
        picks = result.scalars().all()

        items = [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "reason": p.reason,
                "confidence": p.confidence,
                "price_at_pick": p.price_at_pick,
                "next_day_open": p.next_day_open,
                "next_day_close": p.next_day_close,
                "next_day_change_pct": p.next_day_change_pct,
                "pick_date": str(p.pick_date),
            }
            for p in picks
        ]

        return _ok({
            "picks": items,
            "pick_date": str(latest),
            "confidence": picks[0].confidence if picks else None,
        })


@router.get("/ai-picks/history")
async def get_pick_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Get historical AI picks grouped by pick_date with backtest results."""
    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count(func.distinct(AIPick.pick_date)))
        total = (await session.execute(count_stmt)).scalar_one_or_none() or 0

        date_stmt = (
            select(AIPick.pick_date)
            .distinct()
            .order_by(desc(AIPick.pick_date))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        dates = [r[0] for r in (await session.execute(date_stmt)).all()]

        groups = []
        for d in dates:
            stmt = select(AIPick).where(AIPick.pick_date == d).order_by(AIPick.id)
            result = await session.execute(stmt)
            picks = result.scalars().all()
            picks_data = [
                {
                    "id": p.id,
                    "code": p.code,
                    "name": p.name,
                    "reason": p.reason,
                    "confidence": p.confidence,
                    "next_day_open": p.next_day_open,
                    "next_day_close": p.next_day_close,
                    "next_day_change_pct": p.next_day_change_pct,
                }
                for p in picks
            ]
            hit = sum(
                1 for p in picks
                if p.next_day_change_pct is not None and p.next_day_change_pct > 0
            )
            total_backtested = sum(
                1 for p in picks if p.next_day_change_pct is not None
            )
            changes = [
                p.next_day_change_pct for p in picks
                if p.next_day_change_pct is not None
            ]
            avg_change = round(sum(changes) / len(changes), 2) if changes else None

            groups.append({
                "pick_date": str(d),
                "picks": picks_data,
                "count": len(picks),
                "hit_count": hit,
                "total_backtested": total_backtested,
                "avg_change_pct": avg_change,
            })

        return _ok({
            "items": groups,
            "total": total,
            "page": page,
            "page_size": page_size,
        })


@router.get("/ai-picks/stats")
async def get_pick_stats():
    """Get overall AI pick performance statistics."""
    async with AsyncSessionLocal() as session:
        date_stmt = select(func.count(func.distinct(AIPick.pick_date)))
        total_dates = (await session.execute(date_stmt)).scalar_one_or_none() or 0

        stmt = select(AIPick).where(AIPick.next_day_change_pct.isnot(None))
        result = await session.execute(stmt)
        backtested = result.scalars().all()

        total_picks = len(backtested)
        hit_count = sum(1 for p in backtested if p.next_day_change_pct > 0)
        hit_rate = round(hit_count / total_picks * 100, 1) if total_picks > 0 else 0
        avg_change = (
            round(sum(p.next_day_change_pct for p in backtested) / total_picks, 2)
            if total_picks > 0 else 0
        )
        avg_win = (
            round(
                sum(p.next_day_change_pct for p in backtested if p.next_day_change_pct > 0) / hit_count, 2
            )
            if hit_count > 0 else 0
        )
        avg_loss = (
            round(
                sum(p.next_day_change_pct for p in backtested if p.next_day_change_pct < 0)
                / (total_picks - hit_count), 2
            )
            if total_picks > hit_count else 0
        )

        latest = (await session.execute(
            select(func.max(AIPick.pick_date))
        )).scalar_one_or_none()
        today_count = 0
        if latest:
            stmt2 = select(func.count(AIPick.id)).where(AIPick.pick_date == latest)
            today_count = (await session.execute(stmt2)).scalar_one_or_none() or 0

        return _ok({
            "total_dates": total_dates,
            "total_picks_backtested": total_picks,
            "hit_count": hit_count,
            "hit_rate": hit_rate,
            "avg_change_pct": avg_change,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "today_count": today_count,
        })
