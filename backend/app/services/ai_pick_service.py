"""AI pick service — market snapshot collection, DeepSeek prompting, persistence, backtesting."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import desc, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.ai_pick import AIPick
from app.models.stock import StockDaily, StockInfo


# ======================================================================
# Market Snapshot Collection
# ======================================================================

async def _get_tencent_quote(code: str) -> dict | None:
    """Fetch a single stock real-time quote from Tencent finance."""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://qt.gtimg.cn/q={prefix}{code}",
                timeout=5.0,
            )
            text = resp.content.decode("gbk", errors="replace")
        line = text.strip().split(";")[0]
        if "=" not in line:
            return None
        fields = line.split("~")
        if len(fields) < 5:
            return None
        return {
            "code": fields[2],
            "name": fields[1],
            "price": float(fields[3]) if fields[3] else 0,
            "prev_close": float(fields[4]) if fields[4] else 0,
            "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] else 0,
            "volume": float(fields[6]) if fields[6] else 0,
            "amount": float(fields[37]) if len(fields) > 37 and fields[37] else 0,
            "high": float(fields[33]) if len(fields) > 33 and fields[33] else 0,
            "low": float(fields[34]) if len(fields) > 34 and fields[34] else 0,
        }
    except Exception as exc:
        logger.debug(f"Tencent quote failed for {code}: {exc}")
        return None


async def collect_market_snapshot() -> dict:
    """Collect real-time market snapshot at ~14:30.

    Returns dict with: indices, sectors, market_breadth, limit_status,
    north_flow, volume_ratio, dragon_tiger, consecutive_boards, timestamp.
    """
    snapshot: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "indices": [],
        "sectors": [],
        "market_breadth": {},
        "limit_status": {},
        "north_flow": None,
        "volume_ratio": None,
        "dragon_tiger": [],
        "consecutive_boards": [],
    }

    # 1. Major indices
    index_codes = {
        "上证指数": "sh000001", "深证成指": "sz399001",
        "创业板指": "sz399006", "科创50": "sh000688",
    }
    tasks = [_get_tencent_quote(c) for c in index_codes.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for name, r in zip(index_codes.keys(), results):
        if isinstance(r, dict) and r.get("price"):
            snapshot["indices"].append({
                "name": name, "price": r["price"], "change_pct": r["change_pct"],
            })

    # 2. Sector performance
    try:
        from app.services import sector_service
        loop = asyncio.get_running_loop()
        sectors = await loop.run_in_executor(None, sector_service.fetch_sector_performance)
        if sectors:
            sorted_sectors = sorted(sectors, key=lambda s: s.get("change_pct", 0), reverse=True)
            snapshot["sectors"] = [
                {"name": s["name"], "change_pct": s.get("change_pct", 0)}
                for s in sorted_sectors[:10]
            ]
    except Exception as exc:
        logger.warning(f"Failed to fetch sector performance: {exc}")

    # 3. Market breadth & limit counts from DB
    try:
        async with AsyncSessionLocal() as session:
            latest_date_stmt = select(func.max(StockDaily.trade_date))
            latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
            if latest_date:
                stmt = select(
                    StockDaily.code, StockDaily.change_pct
                ).where(StockDaily.trade_date == latest_date)
                rows = (await session.execute(stmt)).all()
                if rows:
                    up = sum(1 for _, pct in rows if pct and pct > 0)
                    down = sum(1 for _, pct in rows if pct and pct < 0)
                    flat = sum(1 for _, pct in rows if pct == 0)
                    limit_up = sum(1 for _, pct in rows if pct and pct >= 9.9)
                    limit_down = sum(1 for _, pct in rows if pct and pct <= -9.9)
                    snapshot["market_breadth"] = {
                        "up": up, "down": down, "flat": flat, "total": len(rows),
                    }
                    snapshot["limit_status"] = {
                        "limit_up": limit_up, "limit_down": limit_down,
                    }
    except Exception as exc:
        logger.warning(f"Failed to compute market breadth: {exc}")

    # 4. North-bound capital flow (try to estimate from index ETF volumes)
    try:
        north_etfs = {
            "北向资金估算(沪)": "sh510050",
            "北向资金估算(深)": "sz159915",
        }
        nf_parts = []
        for label, sym in north_etfs.items():
            q = await _get_tencent_quote(sym)
            if q and q.get("amount"):
                nf_parts.append(f"{label} 成交{q['amount']/100000000:.1f}亿")
        if nf_parts:
            snapshot["north_flow"] = " | ".join(nf_parts)
    except Exception as exc:
        logger.warning(f"Failed to estimate north flow: {exc}")

    # 5. Volume ratio (today's total amount / 5-day avg)
    try:
        async with AsyncSessionLocal() as session:
            latest_date_stmt = select(func.max(StockDaily.trade_date))
            latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
            if latest_date:
                # Today's total amount
                today_sum_stmt = select(func.sum(StockDaily.amount)).where(
                    StockDaily.trade_date == latest_date
                )
                today_sum = (await session.execute(today_sum_stmt)).scalar_one_or_none() or 0

                # Get 5 previous trading days
                date_subq = (
                    select(StockDaily.trade_date)
                    .where(StockDaily.trade_date < latest_date)
                    .distinct()
                    .order_by(desc(StockDaily.trade_date))
                    .limit(5)
                ).subquery()
                avg_stmt = select(func.avg(StockDaily.amount)).where(
                    StockDaily.trade_date.in_(select(date_subq))
                )
                avg_5d = (await session.execute(avg_stmt)).scalar_one_or_none() or today_sum
                if avg_5d > 0:
                    snapshot["volume_ratio"] = round(today_sum / avg_5d, 2)
    except Exception as exc:
        logger.warning(f"Failed to compute volume ratio: {exc}")

    # 6. Dragon tiger board (top active stocks by volume)
    try:
        async with AsyncSessionLocal() as session:
            latest_date_stmt = select(func.max(StockDaily.trade_date))
            latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
            if latest_date:
                # Top volume stocks today with industry
                stmt = (
                    select(StockDaily.code, StockDaily.volume, StockInfo.name,
                           StockDaily.change_pct, StockInfo.industry)
                    .join(StockInfo, StockDaily.code == StockInfo.code)
                    .where(StockDaily.trade_date == latest_date, StockDaily.volume > 0)
                    .order_by(desc(StockDaily.volume))
                    .limit(40)
                )
                rows = (await session.execute(stmt)).all()
                snapshot["dragon_tiger"] = [
                    {"code": c, "name": n, "volume": int(v),
                     "change_pct": round(pct, 2) if pct else 0,
                     "industry": ind or ""}
                    for c, v, n, pct, ind in rows
                ]
    except Exception as exc:
        logger.warning(f"Failed to fetch volume leaders: {exc}")

    # 7. Consecutive boards (today's limit-up stocks)
    try:
        async with AsyncSessionLocal() as session:
            latest_date_stmt = select(func.max(StockDaily.trade_date))
            latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
            if latest_date:
                board_res = await session.execute(
                    select(StockDaily.code, StockInfo.name, StockInfo.industry)
                    .join(StockInfo, StockDaily.code == StockInfo.code)
                    .where(
                        StockDaily.trade_date == latest_date,
                        StockDaily.change_pct >= 9.9,
                    )
                )
                boards = board_res.all()
                snapshot["consecutive_boards"] = [
                    {"code": c, "name": n, "industry": ind or "", "date": str(latest_date)}
                    for c, n, ind in boards[:30]
                ]
    except Exception as exc:
        logger.warning(f"Failed to fetch limit-up stocks: {exc}")

    return snapshot


# ======================================================================
# DeepSeek Prompting
# ======================================================================

AI_PICK_SYSTEM_PROMPT = """你是一个经验丰富的A股短线交易分析师。每天下午2:30，你需要根据当日实时市场数据，选出明天最有可能上涨的股票。

你必须严格返回JSON格式，不要加任何其他文字：
{
  "market_summary": "一句话概括今日市场核心特征",
  "confidence": "high|medium|low",
  "picks": [
    {
      "code": "6位数字代码",
      "name": "股票名称",
      "reason": "推荐理由，80字以内，口语化，说明为什么明天可能涨",
      "confidence": "high|medium|low"
    }
  ]
}
picks数组长度0-5，如果今天市场环境很差、没有把握的标的，返回空数组并confidence设为low。
confidence表示你对自己推荐的把握程度。"""


def _build_pick_prompt(snapshot: dict) -> str:
    """Build the user prompt from market snapshot data."""
    lines = [
        "## 当前时间\n",
        f"{snapshot.get('timestamp', 'N/A')}（下午2:30盘中）\n",
        "## 大盘指数\n",
    ]
    for idx in snapshot.get("indices", []):
        pct = idx.get("change_pct", 0)
        sign = "+" if pct >= 0 else ""
        lines.append(f"- {idx['name']}: {idx['price']:.2f} ({sign}{pct:.2f}%)")

    lines.append("\n## 板块涨跌榜 Top 10\n")
    for s in snapshot.get("sectors", []):
        pct = s.get("change_pct", 0)
        sign = "+" if pct >= 0 else ""
        lines.append(f"- {s['name']}: {sign}{pct:.2f}%")

    breadth = snapshot.get("market_breadth", {})
    lines.append("\n## 涨跌分布\n")
    lines.append(
        f"- 上涨 {breadth.get('up','?')} / 平盘 {breadth.get('flat','?')} / 下跌 {breadth.get('down','?')}"
    )

    limit = snapshot.get("limit_status", {})
    lines.append(f"- 涨停 {limit.get('limit_up','?')} 家 / 跌停 {limit.get('limit_down','?')} 家")

    nf = snapshot.get("north_flow")
    if nf:
        lines.append(f"\n## 北向资金参考\n{nf}")

    vr = snapshot.get("volume_ratio")
    if vr is not None:
        label = "放量" if vr > 1.2 else ("缩量" if vr < 0.8 else "持平")
        lines.append(f"\n## 成交量\n今日成交额 / 前5日均值 = {vr:.2f}（{label}）")

    dt = snapshot.get("dragon_tiger", [])
    if dt:
        # Group by industry for diversified view
        from collections import defaultdict
        by_industry = defaultdict(list)
        for d in dt:
            if isinstance(d, dict):
                ind = d.get("industry", "其他")
                by_industry[ind].append(d)
        lines.append(f"\n## 各板块活跃个股（按成交量排序，共{len(dt)}只）\n")
        for ind, stocks in sorted(by_industry.items(), key=lambda x: -len(x[1])):
            stock_strs = []
            for s in stocks[:4]:  # max 4 per sector
                pct = s.get("change_pct", 0)
                sign = "+" if pct >= 0 else ""
                stock_strs.append(f"{s.get('name','')}({sign}{pct:.1f}%)")
            lines.append(f"- **{ind}**（{len(stocks)}只）: {', '.join(stock_strs)}")

    cb = snapshot.get("consecutive_boards", [])
    if cb:
        from collections import defaultdict as _dd
        by_ind = _dd(list)
        for b in cb[:20]:
            if isinstance(b, dict):
                ind = b.get("industry", "") or "其他"
                by_ind[ind].append(f"{b.get('name','')}({b.get('code','')})")

        if by_ind:
            lines.append("\n## 今日涨停板（按行业）\n")
            for ind, stocks in sorted(by_ind.items(), key=lambda x: -len(x[1])):
                lines.append(f"- **{ind}**: {', '.join(stocks)}")

    lines.append("\n---")
    lines.append("请基于以上数据，选出明天大概率上涨的股票（0-5只）。尽量跨板块分散，优先选不同行业的强势标的。严格返回JSON格式。")
    return "\n".join(lines)


async def call_deepseek_for_picks(snapshot: dict) -> dict | None:
    """Call DeepSeek API and return parsed JSON, or None on failure."""
    if not settings.deepseek_api_key:
        logger.warning("DeepSeek API key not configured, skipping AI picks")
        return None

    prompt = _build_pick_prompt(snapshot)
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": AI_PICK_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1500,
    }

    async def _call_once() -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.deepseek_base_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    for attempt in (1, 2):
        try:
            raw = await _call_once()
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()
            result = json.loads(raw)
            if "market_summary" not in result or "picks" not in result:
                raise ValueError("Missing required fields in response")
            picks = result["picks"]
            if not isinstance(picks, list):
                raise ValueError("picks is not a list")
            for p in picks:
                if not all(k in p for k in ("code", "name", "reason")):
                    raise ValueError(f"Pick missing required field: {p}")
            logger.info(
                f"AI picks generated: {len(picks)} stocks, confidence={result.get('confidence')}"
            )
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"AI pick parsing failed (attempt {attempt}/2): {exc}")
            if attempt == 1:
                continue
        except Exception as exc:
            logger.error(f"DeepSeek API error (attempt {attempt}/2): {exc}")
            break

    logger.error("AI pick generation failed after 2 attempts")
    return None


# ======================================================================
# Persistence & Notification
# ======================================================================

async def save_ai_picks(pick_date: date, result: dict) -> int:
    """Save AI picks to database. Returns count of saved picks."""
    picks = result.get("picks", [])
    if not picks:
        logger.info(f"No AI picks for {pick_date} (AI determined no opportunities)")
        return 0

    async with AsyncSessionLocal() as session:
        saved = 0
        for p in picks:
            pick = AIPick(
                pick_date=pick_date,
                code=p["code"],
                name=p.get("name", ""),
                reason=p.get("reason", ""),
                confidence=p.get("confidence", result.get("confidence", "medium")),
                price_at_pick=None,
            )
            session.add(pick)
            saved += 1
        await session.commit()
        logger.info(f"Saved {saved} AI picks for {pick_date}")
        return saved


def format_ai_pick_message(pick_date: date, result: dict) -> str:
    """Format AI pick results into WeChat Work markdown message."""
    picks = result.get("picks", [])
    market_summary = result.get("market_summary", "")
    confidence = result.get("confidence", "medium")
    confidence_label = {"high": "较高", "medium": "中等", "low": "较低"}.get(confidence, confidence)

    lines = [
        f"## AI 明日选股推荐 ({pick_date})",
        "",
        f"**市场概况** {market_summary}",
        "",
    ]

    if not picks:
        lines.append("AI 判断今日不适合入场，建议观望。")
    else:
        lines.append(f"**推荐标的** (把握: {confidence_label})")
        lines.append("")
        for i, p in enumerate(picks, 1):
            lines.append(f"**{i}. {p['code']} {p.get('name', '')}**")
            lines.append(f"> {p.get('reason', '')}")
            lines.append("")

    lines.append("---")
    lines.append("以上为 AI 基于实时行情数据的分析预测，仅供参考，不构成投资建议。")
    return "\n".join(lines)


async def push_ai_pick_notification(pick_date: date, result: dict) -> bool:
    """Push AI pick results to WeChat Work webhook."""
    if not settings.wechat_webhook_url:
        logger.debug("No webhook URL configured, skipping AI pick notification")
        return False

    message = format_ai_pick_message(pick_date, result)
    from app.services.notification_service import send_wechat_work
    return send_wechat_work(settings.wechat_webhook_url, message)


# ======================================================================
# Backtesting
# ======================================================================

async def _get_stock_close_on_date(code: str, target_date: date) -> float | None:
    """Get a stock's close price on a specific date."""
    async with AsyncSessionLocal() as session:
        stmt = select(StockDaily.close).where(
            StockDaily.code == code,
            StockDaily.trade_date == target_date,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def backtest_ai_picks_open() -> int:
    """Fill next_day_open for picks made on the most recent pick_date."""
    async with AsyncSessionLocal() as session:
        stmt = select(AIPick.pick_date).order_by(AIPick.pick_date.desc()).limit(1)
        latest = (await session.execute(stmt)).scalar_one_or_none()
        if not latest:
            logger.debug("No AI picks to backtest (open)")
            return 0

        stmt = select(AIPick).where(
            AIPick.pick_date == latest,
            AIPick.next_day_open.is_(None),
        )
        result = await session.execute(stmt)
        picks = result.scalars().all()

        updated = 0
        today = date.today()
        for pick in picks:
            open_price = await _get_stock_close_on_date(pick.code, today)
            if open_price is not None:
                pick.next_day_open = open_price
                # Also fill price_at_pick if not set
                if pick.price_at_pick is None:
                    pick.price_at_pick = open_price
                updated += 1

        if updated:
            await session.commit()
            logger.info(f"Backtest open: updated {updated}/{len(picks)} picks for {latest}")
        return updated


async def backtest_ai_picks_close() -> int:
    """Fill next_day_close + change_pct for picks on the most recent pick_date."""
    async with AsyncSessionLocal() as session:
        stmt = select(AIPick.pick_date).order_by(AIPick.pick_date.desc()).limit(1)
        latest = (await session.execute(stmt)).scalar_one_or_none()
        if not latest:
            logger.debug("No AI picks to backtest (close)")
            return 0

        stmt = select(AIPick).where(
            AIPick.pick_date == latest,
            AIPick.next_day_close.is_(None),
        )
        result = await session.execute(stmt)
        picks = result.scalars().all()

        updated = 0
        today = date.today()
        for pick in picks:
            close_price = await _get_stock_close_on_date(pick.code, today)
            if close_price is None:
                continue
            pick.next_day_close = close_price
            pick.backtest_at = datetime.now()
            if pick.next_day_open and pick.next_day_open > 0:
                pick.next_day_change_pct = round(
                    (close_price - pick.next_day_open) / pick.next_day_open * 100, 2
                )
            updated += 1

        if updated:
            await session.commit()
            logger.info(f"Backtest close: updated {updated}/{len(picks)} picks for {latest}")
        return updated


# ======================================================================
# Main scheduled task entry point
# ======================================================================

async def run_ai_pick_task() -> None:
    """Scheduled task: collect market snapshot → AI picks → save → notify."""
    logger.info("Starting AI pick task (14:30)")

    try:
        snapshot = await collect_market_snapshot()
        logger.info(
            f"Market snapshot: indices={len(snapshot.get('indices',[]))} "
            f"sectors={len(snapshot.get('sectors',[]))} "
            f"breadth={snapshot.get('market_breadth',{})}"
        )

        result = await call_deepseek_for_picks(snapshot)
        if result is None:
            logger.warning("AI pick generation returned no result")
            return

        today = date.today()
        saved = await save_ai_picks(today, result)
        await push_ai_pick_notification(today, result)

        logger.info(f"AI pick task completed: {saved} picks saved")
    except Exception as exc:
        logger.error(f"AI pick task failed: {exc}")
