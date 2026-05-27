"""Alert service - checks alert rules against current rankings and factors."""

from __future__ import annotations

import json
from datetime import date, datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertLog, AlertRule
from app.models.stock import FactorValue, StockInfo, StockRanking


async def check_alerts(session: AsyncSession) -> list[dict]:
    """Check all enabled alert rules and create AlertLog entries for triggers.

    Returns list of triggered alerts: [{rule_id, rule_name, code, name, message}].
    """
    stmt = select(AlertRule).where(AlertRule.enabled == True)
    result = await session.execute(stmt)
    rules = result.scalars().all()

    if not rules:
        return []

    triggers: list[dict] = []

    for rule in rules:
        params = json.loads(rule.params) if rule.params else {}
        try:
            if rule.rule_type == "rank_change":
                triggered = await _check_rank_change(session, rule, params)
            elif rule.rule_type == "score_threshold":
                triggered = await _check_score_threshold(session, rule, params)
            elif rule.rule_type == "factor_anomaly":
                triggered = await _check_factor_anomaly(session, rule, params)
            else:
                logger.warning(f"Unknown alert rule type: {rule.rule_type}")
                continue

            triggers.extend(triggered)
        except Exception as e:
            logger.error(f"Alert check failed for rule {rule.id} ({rule.name}): {e}")

    if triggers:
        for t in triggers:
            session.add(AlertLog(
                rule_id=t["rule_id"],
                code=t["code"],
                name=t["name"],
                message=t["message"],
            ))
        triggered_rule_ids = {t["rule_id"] for t in triggers}
        for rule in rules:
            if rule.id in triggered_rule_ids:
                rule.triggered_at = datetime.utcnow()
        await session.commit()

    return triggers


async def _check_rank_change(
    session: AsyncSession, rule: AlertRule, params: dict,
) -> list[dict]:
    """Check if any stock's rank changed more than threshold since last date."""
    threshold = params.get("threshold", 10)
    direction = params.get("direction", "up")

    date_stmt = (
        select(StockRanking.rank_date)
        .distinct()
        .order_by(StockRanking.rank_date.desc())
        .limit(2)
    )
    date_result = await session.execute(date_stmt)
    dates = [r[0] for r in date_result.all()]
    if len(dates) < 2:
        return []

    today_r, prev_r = dates[0], dates[1]

    today_stmt = select(StockRanking.code, StockRanking.rank_position, StockRanking.total_score).where(
        StockRanking.rank_date == today_r
    )
    prev_stmt = select(StockRanking.code, StockRanking.rank_position).where(
        StockRanking.rank_date == prev_r
    )

    today_result = await session.execute(today_stmt)
    prev_result = await session.execute(prev_stmt)

    today_map = {r[0]: (r[1], r[2]) for r in today_result.all()}
    prev_map = {r[0]: r[1] for r in prev_result.all()}

    codes = list(today_map.keys())
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(codes))
    name_result = await session.execute(name_stmt)
    name_map = {r[0]: r[1] for r in name_result.all()}

    triggers = []
    for code, (rank, score) in today_map.items():
        if code not in prev_map:
            continue
        prev_rank = prev_map[code]
        change = prev_rank - rank
        if direction == "up" and change >= threshold:
            msg = f"排名上升 {change} 位 ({prev_rank}→{rank})，当前评分 {score:.1f}"
            triggers.append({"rule_id": rule.id, "rule_name": rule.name, "code": code, "name": name_map.get(code, ""), "message": msg})
        elif direction == "down" and change <= -threshold:
            msg = f"排名下降 {abs(change)} 位 ({prev_rank}→{rank})，当前评分 {score:.1f}"
            triggers.append({"rule_id": rule.id, "rule_name": rule.name, "code": code, "name": name_map.get(code, ""), "message": msg})

    return triggers


async def _check_score_threshold(
    session: AsyncSession, rule: AlertRule, params: dict,
) -> list[dict]:
    """Check if any stock's total score exceeds or falls below threshold."""
    threshold = params.get("threshold", 80)
    direction = params.get("direction", "above")

    date_stmt = select(func.max(StockRanking.rank_date))
    date_result = await session.execute(date_stmt)
    latest_date = date_result.scalar_one_or_none()
    if not latest_date:
        return []

    stmt = select(StockRanking).where(StockRanking.rank_date == latest_date)
    if direction == "above":
        stmt = stmt.where(StockRanking.total_score >= threshold)
    else:
        stmt = stmt.where(StockRanking.total_score <= threshold)

    result = await session.execute(stmt)
    stocks = result.scalars().all()

    codes = [s.code for s in stocks]
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(codes))
    name_result = await session.execute(name_stmt)
    name_map = {r[0]: r[1] for r in name_result.all()}

    triggers = []
    for s in stocks:
        op = "≥" if direction == "above" else "≤"
        msg = f"综合评分 {s.total_score:.1f} {op} {threshold}，排名 #{s.rank_position}"
        triggers.append({"rule_id": rule.id, "rule_name": rule.name, "code": s.code, "name": name_map.get(s.code, ""), "message": msg})

    return triggers


async def _check_factor_anomaly(
    session: AsyncSession, rule: AlertRule, params: dict,
) -> list[dict]:
    """Check if a specific factor value is anomalous."""
    factor_name = params.get("factor_name", "rsi")
    operator = params.get("operator", ">")
    value = params.get("value", 0.8)

    stmt = select(FactorValue).where(FactorValue.factor_name == factor_name)
    result = await session.execute(stmt)
    factors = result.scalars().all()

    codes = [f.code for f in factors]
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(codes))
    name_result = await session.execute(name_stmt)
    name_map = {r[0]: r[1] for r in name_result.all()}

    triggers = []
    for f in factors:
        hit = False
        if operator == ">" and f.value > value:
            hit = True
        elif operator == "<" and f.value < value:
            hit = True
        elif operator == ">=" and f.value >= value:
            hit = True
        elif operator == "<=" and f.value <= value:
            hit = True

        if hit:
            msg = f"因子 {factor_name} = {f.value:.3f} {operator} {value}"
            triggers.append({"rule_id": rule.id, "rule_name": rule.name, "code": f.code, "name": name_map.get(f.code, ""), "message": msg})

    return triggers


def format_alert_message(triggers: list[dict]) -> str:
    """Format triggered alerts into a WeChat notification message."""
    if not triggers:
        return ""

    lines = ["## 🚨 智能预警", ""]
    for t in triggers[:20]:
        lines.append(f"- **{t['name']}**({t['code']}): {t['message']}")

    if len(triggers) > 20:
        lines.append(f"\n... 共 {len(triggers)} 条预警")

    return "\n".join(lines)
