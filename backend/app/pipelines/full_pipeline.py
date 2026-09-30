"""Composite pipeline: factors → rankings → alerts, as one job.

This is what ``POST /rankings/compute`` and the 15:25 daily cron both trigger.
Having a single entry point is the whole point of the pipeline layer: the two
callers previously ran *separate copies* of this sequence.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from loguru import logger

from app.core.jobs import JobContext
from app.pipelines.factor_pipeline import run_factor_pipeline, run_ranking_pipeline


async def run_full_ranking_pipeline(
    ctx: JobContext,
    *,
    trading_date: date | None = None,
    concurrency: int = 12,
) -> dict[str, Any]:
    """Factor computation followed by ranking, then alert evaluation.

    Each phase gets its own slice of the 0-100 progress bar so the UI advances
    monotonically instead of resetting between phases.
    """
    target = trading_date or date.today()

    # Phase 1 — factors (0-70%)
    factors = await run_factor_pipeline(ctx, trading_date=target, concurrency=concurrency)
    ctx.raise_if_cancelled()

    # Phase 2 — rankings (70-95%)
    await ctx.report(70, 100, "计算排名…")
    rankings = await run_ranking_pipeline(ctx, trading_date=target)
    ctx.raise_if_cancelled()

    # Phase 3 — alerts (95-100%), best-effort
    await ctx.report(95, 100, "检查预警…")
    alert_count = 0
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.alert_service import check_alerts, format_alert_message

        async with AsyncSessionLocal() as session:
            triggers = await check_alerts(session)

        if triggers:
            alert_count = len(triggers)
            message = format_alert_message(triggers)
            if message:
                from app.core.config import settings
                from app.services.notification_service import send_wechat_work

                if settings.wechat_webhook_url:
                    send_wechat_work(settings.wechat_webhook_url, message)
        else:
            logger.info("No alert triggers")
    except Exception as exc:
        logger.warning(f"Alert phase failed (non-fatal): {exc}")

    await ctx.report(100, 100, "完成")
    return {
        "date": str(target),
        "factors": factors,
        "rankings": rankings,
        "alerts_triggered": alert_count,
    }
