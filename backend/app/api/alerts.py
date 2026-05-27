"""Alert API routes."""

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.alert import AlertLog, AlertRule

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/alerts/rules")
async def list_alert_rules(session: AsyncSession = Depends(get_db)):
    stmt = select(AlertRule).order_by(AlertRule.created_at.desc())
    result = await session.execute(stmt)
    rules = result.scalars().all()
    return _ok([
        {
            "id": r.id,
            "name": r.name,
            "rule_type": r.rule_type,
            "params": json.loads(r.params) if r.params else {},
            "enabled": r.enabled,
            "notify_wechat": r.notify_wechat,
            "created_at": str(r.created_at),
            "triggered_at": str(r.triggered_at) if r.triggered_at else None,
        }
        for r in rules
    ])


@router.post("/alerts/rules")
async def create_alert_rule(
    name: str = Query(..., min_length=1, max_length=100),
    rule_type: str = Query(..., pattern="^(rank_change|score_threshold|factor_anomaly)$"),
    params: str = Query(..., description="JSON string of rule parameters"),
    enabled: bool = Query(default=True),
    notify_wechat: bool = Query(default=True),
    session: AsyncSession = Depends(get_db),
):
    # Validate params is valid JSON
    try:
        json.loads(params)
    except json.JSONDecodeError:
        return _err("params must be valid JSON")

    rule = AlertRule(
        name=name,
        rule_type=rule_type,
        params=params,
        enabled=enabled,
        notify_wechat=notify_wechat,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _ok({"id": rule.id}, "Alert rule created")


@router.put("/alerts/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    name: str = Query(default=None),
    params: str = Query(default=None),
    enabled: bool = Query(default=None),
    notify_wechat: bool = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        return _err("Alert rule not found", 404)

    if name is not None:
        rule.name = name
    if params is not None:
        try:
            json.loads(params)
        except json.JSONDecodeError:
            return _err("params must be valid JSON")
        rule.params = params
    if enabled is not None:
        rule.enabled = enabled
    if notify_wechat is not None:
        rule.notify_wechat = notify_wechat

    await session.commit()
    return _ok({"id": rule.id}, "Alert rule updated")


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_db),
):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        return _err("Alert rule not found", 404)

    await session.delete(rule)
    await session.commit()
    return _ok({"id": rule_id}, "Alert rule deleted")


@router.get("/alerts/logs")
async def get_alert_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    # Count
    count_stmt = select(func.count(AlertLog.id))
    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    # Query with join to get rule name
    stmt = (
        select(AlertLog, AlertRule.name.label("rule_name"))
        .join(AlertRule, AlertLog.rule_id == AlertRule.id)
        .order_by(AlertLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.all()

    items = [
        {
            "id": log.id,
            "rule_name": rule_name,
            "code": log.code,
            "name": log.name,
            "message": log.message,
            "created_at": str(log.created_at),
        }
        for log, rule_name in rows
    ]

    return _ok({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    })


@router.post("/alerts/check")
async def manual_check_alerts(session: AsyncSession = Depends(get_db)):
    """Manually trigger alert checking."""
    from app.services.alert_service import check_alerts, format_alert_message

    triggers = await check_alerts(session)
    message = format_alert_message(triggers) if triggers else ""

    return _ok({
        "triggered": len(triggers),
        "triggers": triggers[:20],
        "message": message,
    })
