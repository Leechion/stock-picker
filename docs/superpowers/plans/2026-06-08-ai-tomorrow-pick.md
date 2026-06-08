# AI 明日选股推荐 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每天下午 2:30 AI 基于实时市场行情自主选出 0-5 只明天大概率上涨的股票，企微推送 + 前端展示 + 次日回测追踪。

**Architecture:** 纯增量开发，新增独立的 model / service / API / frontend 文件，仅在 scheduler.py 末尾追加 3 个 job、在 main.py 追加 1 行注册路由、在前端 router 追加 1 条路由、在 App.vue 追加 1 个菜单项。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy async / APScheduler / DeepSeek API / Vue 3 / TypeScript / Element Plus

**Spec:** `docs/superpowers/specs/2026-06-08-ai-tomorrow-pick-design.md`

---

### Task 1: Create AI Pick data model

**Files:**
- Create: `backend/app/models/ai_pick.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the model file**

```python
"""AI pick model — stores daily AI stock recommendations for tomorrow."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIPick(Base):
    __tablename__ = "ai_picks"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pick_date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_at_pick: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    backtest_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

- [ ] **Step 2: Register model in __init__.py**

In `backend/app/models/__init__.py`, append after the existing `AlertRule, AlertLog` imports:

```python
from app.models.ai_pick import AIPick

__all__ = [
    "StockInfo", "StockDaily", "FactorValue", "StockRanking", "FactorType",
    "TradingAccount", "Position", "TradeLog",
    "AlertRule", "AlertLog",
    "AIPick",
]
```

- [ ] **Step 3: Verify model imports correctly**

Run: `cd "backend" && python -c "from app.models.ai_pick import AIPick; print('OK')"`
Expected: `OK` with no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/ai_pick.py backend/app/models/__init__.py
git commit -m "feat: add AIPick model for AI stock recommendations"
```

---

### Task 2: Create AI pick service (core logic)

**Files:**
- Create: `backend/app/services/ai_pick_service.py`

- [ ] **Step 1: Create the service file with market data collector**

```python
"""AI pick service — market snapshot collection, DeepSeek prompting, persistence, backtesting."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import func, select

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

    # 2. Sector performance (reuse sector_service)
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

    # 4. North-bound capital flow (approximate via sh513050 / sz159915 ETF volumes)
    try:
        from app.services.capital_flow import fetch_north_flow_rough
        loop = asyncio.get_running_loop()
        north = await loop.run_in_executor(None, fetch_north_flow_rough)
        if north:
            snapshot["north_flow"] = north
    except Exception as exc:
        logger.warning(f"Failed to fetch north flow: {exc}")

    # 5. Volume ratio (today's total volume / 5-day avg)
    try:
        async with AsyncSessionLocal() as session:
            latest_date_stmt = select(func.max(StockDaily.trade_date))
            latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
            if latest_date:
                stmt = select(func.sum(StockDaily.amount)).where(
                    StockDaily.trade_date == latest_date
                )
                today_sum = (await session.execute(stmt)).scalar_one_or_none() or 0
                stmt_5d = select(func.avg(StockDaily.amount)).where(
                    StockDaily.trade_date < latest_date
                ).limit(5)
                # better: get last 5 trading days
                from sqlalchemy import desc
                sub = (
                    select(StockDaily.trade_date)
                    .distinct()
                    .order_by(desc(StockDaily.trade_date))
                    .limit(6)
                ).subquery()
                stmt_5d_amt = select(func.avg(StockDaily.amount)).where(
                    StockDaily.trade_date.in_(select(sub.c.trade_date)),
                    StockDaily.trade_date < latest_date,
                )
                avg_5d = (await session.execute(stmt_5d_amt)).scalar_one_or_none() or today_sum
                if avg_5d > 0:
                    snapshot["volume_ratio"] = round(today_sum / avg_5d, 2)
    except Exception as exc:
        logger.warning(f"Failed to compute volume ratio: {exc}")

    # 6. Dragon tiger board
    try:
        from app.services.capital_flow import fetch_dragon_tiger
        loop = asyncio.get_running_loop()
        dt = await loop.run_in_executor(None, fetch_dragon_tiger)
        if dt:
            snapshot["dragon_tiger"] = dt[:20]
    except Exception as exc:
        logger.warning(f"Failed to fetch dragon tiger: {exc}")

    # 7. Consecutive boards (stocks that hit limit up for N consecutive days)
    try:
        async with AsyncSessionLocal() as session:
            # get last 5 trading dates
            date_stmt = (
                select(StockDaily.trade_date)
                .distinct()
                .order_by(StockDaily.trade_date.desc())
                .limit(5)
            )
            dates = [r[0] for r in (await session.execute(date_stmt)).all()]
            if len(dates) >= 2:
                board_res = await session.execute(
                    select(StockDaily.code, StockInfo.name)
                    .join(StockInfo, StockDaily.code == StockInfo.code)
                    .where(
                        StockDaily.trade_date == dates[0],
                        StockDaily.change_pct >= 9.9,
                    )
                )
                boards = board_res.all()
                snapshot["consecutive_boards"] = [
                    {"code": c, "name": n, "date": str(dates[0])}
                    for c, n in boards[:30]
                ]
    except Exception as exc:
        logger.warning(f"Failed to fetch consecutive boards: {exc}")

    return snapshot
```

- [ ] **Step 2: Add DeepSeek prompt builder and caller**

Append to the same file:

```python
# ======================================================================
# DeepSeek Prompting
# ======================================================================

AI_PICK_SYSTEM_PROMPT = """你是一个经验丰富的A股短线交易分析师。每天下午2:30，你需要根据当日实时市场数据，选出明天最有可能上涨的股票。

选股原则：
1. 优先关注当日资金持续流入的板块和个股
2. 关注板块联动效应，热点板块中的补涨机会
3. 技术面关注突破关键均线或压力位的标的
4. 回避已经连续大涨或涨停的个股（追高风险大）
5. 大盘环境好时积极，大盘弱势时谨慎

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
    lines.append(f"\n## 涨跌分布\n")
    lines.append(f"- 上涨 {breadth.get('up','?')} / 平盘 {breadth.get('flat','?')} / 下跌 {breadth.get('down','?')}")

    limit = snapshot.get("limit_status", {})
    lines.append(f"- 涨停 {limit.get('limit_up','?')} 家 / 跌停 {limit.get('limit_down','?')} 家")

    nf = snapshot.get("north_flow")
    if nf is not None:
        lines.append(f"\n## 北向资金\n{nf}")

    vr = snapshot.get("volume_ratio")
    if vr is not None:
        lines.append(f"\n## 成交量\n今日成交额 / 前5日均值 = {vr:.2f}")

    dt = snapshot.get("dragon_tiger", [])
    if dt:
        lines.append(f"\n## 龙虎榜活跃度\n上榜 {len(dt)} 只")
        for d in dt[:10]:
            if isinstance(d, dict):
                lines.append(f"- {d.get('code','')} {d.get('name','')}")

    cb = snapshot.get("consecutive_boards", [])
    if cb:
        names = [f"{b['name']}({b['code']})" for b in cb[:10] if isinstance(b, dict)]
        lines.append(f"\n## 今日涨停板（部分）\n{', '.join(names)}")

    lines.append("\n---")
    lines.append("请基于以上数据，选出明天大概率上涨的股票（0-5只），返回JSON。")
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

    # Try up to 2 times
    for attempt in (1, 2):
        try:
            raw = await _call_once()
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()
            result = json.loads(raw)
            # Validate structure
            if "market_summary" not in result or "picks" not in result:
                raise ValueError("Missing required fields in response")
            picks = result["picks"]
            if not isinstance(picks, list):
                raise ValueError("picks is not a list")
            for p in picks:
                if not all(k in p for k in ("code", "name", "reason")):
                    raise ValueError(f"Pick missing required field: {p}")
            logger.info(f"AI picks generated: {len(picks)} stocks, confidence={result.get('confidence')}")
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
```

- [ ] **Step 3: Add save and push functions**

Append to the same file:

```python
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
                price_at_pick=None,  # will be filled by backtest if needed
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
        f"## 🤖 AI 明日选股推荐 ({pick_date})",
        "",
        f"**📊 市场概况：** {market_summary}",
        "",
    ]

    if not picks:
        lines.append("⚠️ **AI 判断今日不适合入场，建议观望。**")
    else:
        lines.append(f"**🏆 推荐标的** (AI 把握: {confidence_label})")
        lines.append("")
        for i, p in enumerate(picks, 1):
            lines.append(f"**{i}. {p['code']} {p.get('name', '')}**")
            lines.append(f"> {p.get('reason', '')}")
            lines.append("")

    lines.append("---")
    lines.append("⚠️ 以上为 AI 基于实时行情数据的分析预测，仅供参考，不构成投资建议。")
    return "\n".join(lines)


async def push_ai_pick_notification(pick_date: date, result: dict) -> bool:
    """Push AI pick results to WeChat Work webhook."""
    if not settings.wechat_webhook_url:
        logger.debug("No webhook URL configured, skipping AI pick notification")
        return False

    message = format_ai_pick_message(pick_date, result)
    from app.services.notification_service import send_wechat_work
    return send_wechat_work(settings.wechat_webhook_url, message)
```

- [ ] **Step 4: Add backtest functions**

Append to the same file:

```python
# ======================================================================
# Backtesting (next-day price comparison)
# ======================================================================

async def _get_stock_close_on_date(code: str, target_date: date) -> float | None:
    """Get a stock's close price on a specific date."""
    from sqlalchemy import select as sa_select
    from app.models.stock import StockDaily

    async with AsyncSessionLocal() as session:
        stmt = sa_select(StockDaily.close).where(
            StockDaily.code == code,
            StockDaily.trade_date == target_date,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def backtest_ai_picks_open() -> int:
    """Fill next_day_open for picks made yesterday."""
    yesterday = date.today()
    # Find the most recent pick_date (which is yesterday or earlier)
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
        for pick in picks:
            open_price = await _get_stock_close_on_date(pick.code, date.today())
            if open_price is not None:
                pick.next_day_open = open_price
                updated += 1

        if updated:
            await session.commit()
            logger.info(f"Backtest open: updated {updated}/{len(picks)} picks for {latest}")
        return updated


async def backtest_ai_picks_close() -> int:
    """Fill next_day_close + change_pct for picks made on the last trading day."""
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
        for pick in picks:
            close_price = await _get_stock_close_on_date(pick.code, date.today())
            if close_price is not None and pick.price_at_pick:
                pick.next_day_close = close_price
                pick.next_day_change_pct = round(
                    (close_price - pick.price_at_pick) / pick.price_at_pick * 100, 2
                )
                pick.backtest_at = datetime.now()
                updated += 1
            elif close_price is not None:
                pick.next_day_close = close_price
                pick.backtest_at = datetime.now()
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
        if saved > 0:
            await push_ai_pick_notification(today, result)
        else:
            # Still push when AI decides no picks (market summary only)
            await push_ai_pick_notification(today, result)

        logger.info(f"AI pick task completed: {saved} picks")
    except Exception as exc:
        logger.error(f"AI pick task failed: {exc}")
```

- [ ] **Step 5: Verify service imports**

Run: `cd "backend" && python -c "from app.services.ai_pick_service import run_ai_pick_task, collect_market_snapshot; print('OK')"`
Expected: `OK` with no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_pick_service.py
git commit -m "feat: add AI pick service with market snapshot, DeepSeek integration, backtesting"
```

---

### Task 3: Create AI picks API routes

**Files:**
- Create: `backend/app/api/ai_picks.py`

- [ ] **Step 1: Create the API file**

```python
"""AI picks API routes."""
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.ai_pick import AIPick

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/ai-picks/today")
async def get_today_picks(
    session: AsyncSession = Query(default=None),
):
    """Get today's AI picks. Returns empty list if no picks yet."""
    # Use injected session if available, otherwise create one
    if session is None:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            return await _get_today_picks(s)

    return await _get_today_picks(session)


async def _get_today_picks(session: AsyncSession):
    today = date.today()

    # Get most recent pick_date (could be today or last trading day)
    stmt = select(func.max(AIPick.pick_date))
    latest = (await session.execute(stmt)).scalar_one_or_none()

    if not latest:
        return _ok({"picks": [], "market_summary": "", "pick_date": str(today), "confidence": None})

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
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Get total distinct pick_dates
        count_stmt = select(func.count(func.distinct(AIPick.pick_date)))
        total = (await session.execute(count_stmt)).scalar_one_or_none() or 0

        # Get distinct pick_dates with pagination
        date_stmt = (
            select(AIPick.pick_date)
            .distinct()
            .order_by(desc(AIPick.pick_date))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        dates = [r[0] for r in (await session.execute(date_stmt)).all()]

        # For each date, get the picks
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
                    "next_day_change_pct": p.next_day_change_pct,
                }
                for p in picks
            ]
            # Compute day hit rate
            hit = sum(1 for p in picks if p.next_day_change_pct is not None and p.next_day_change_pct > 0)
            total_picks = sum(1 for p in picks if p.next_day_change_pct is not None)
            avg_change = (
                round(sum(p.next_day_change_pct for p in picks if p.next_day_change_pct is not None) / total_picks, 2)
                if total_picks > 0 else None
            )

            groups.append({
                "pick_date": str(d),
                "picks": picks_data,
                "count": len(picks),
                "hit_count": hit,
                "total_backtested": total_picks,
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
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Total distinct pick dates
        date_stmt = select(func.count(func.distinct(AIPick.pick_date)))
        total_dates = (await session.execute(date_stmt)).scalar_one_or_none() or 0

        # Total picks with backtest results
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
            round(sum(p.next_day_change_pct for p in backtested if p.next_day_change_pct > 0) / hit_count, 2)
            if hit_count > 0 else 0
        )
        avg_loss = (
            round(sum(p.next_day_change_pct for p in backtested if p.next_day_change_pct < 0) / (total_picks - hit_count), 2)
            if total_picks > hit_count else 0
        )

        # Today's picks
        today_stmt = select(func.max(AIPick.pick_date))
        latest = (await session.execute(today_stmt)).scalar_one_or_none()
        today_count = 0
        if latest:
            stmt = select(func.count(AIPick.id)).where(AIPick.pick_date == latest)
            today_count = (await session.execute(stmt)).scalar_one_or_none() or 0

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
```

- [ ] **Step 2: Verify API imports**

Run: `cd "backend" && python -c "from app.api.ai_picks import router; print('OK')"`
Expected: `OK` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/ai_picks.py
git commit -m "feat: add AI picks API routes (today, history, stats)"
```

---

### Task 4: Register scheduler jobs & API router

**Files:**
- Modify: `backend/app/core/scheduler.py` (append after the last `scheduler.add_job` block, before `scheduler.start()`)
- Modify: `backend/app/main.py` (add 1 import + 1 router registration)

- [ ] **Step 1: Add 3 scheduler jobs**

In `backend/app/core/scheduler.py`, insert after the `run_daily_summary` job (after line 397, before `scheduler.start()` on line 398):

```python
    # AI tomorrow pick jobs
    scheduler.add_job(
        run_ai_pick_task,
        trigger="cron",
        hour=14,
        minute=30,
        day_of_week="mon-fri",
        id="ai_pick",
        name="AI pick for tomorrow",
        replace_existing=True,
    )
    scheduler.add_job(
        backtest_ai_picks_open,
        trigger="cron",
        hour=9,
        minute=26,
        day_of_week="mon-fri",
        id="ai_pick_backtest_open",
        name="Backtest AI picks - open price",
        replace_existing=True,
    )
    scheduler.add_job(
        backtest_ai_picks_close,
        trigger="cron",
        hour=15,
        minute=5,
        day_of_week="mon-fri",
        id="ai_pick_backtest_close",
        name="Backtest AI picks - close price",
        replace_existing=True,
    )
```

And add the imports at the top of the file (after the existing imports, around line 12):

```python
from app.services.ai_pick_service import run_ai_pick_task, backtest_ai_picks_open, backtest_ai_picks_close
```

- [ ] **Step 2: Register API router in main.py**

In `backend/app/main.py`, add the import on line 12 (after the existing API imports):

```python
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor, wechat, alerts, ai_picks
```

And add the router registration after line 101 (after `alerts`):

```python
    app.include_router(ai_picks.router, prefix="/api")
```

- [ ] **Step 3: Verify scheduler and app still start correctly**

Run: `cd "backend" && python -c "from app.core.scheduler import register_scheduler; print('scheduler OK')"`
Expected: `scheduler OK`

Run: `cd "backend" && python -c "from app.main import app; print('app OK')"`
Expected: `app OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/scheduler.py backend/app/main.py
git commit -m "feat: register AI pick scheduler jobs and API router"
```

---

### Task 5: Create frontend API module

**Files:**
- Create: `frontend/src/api/aiPicks.ts`

- [ ] **Step 1: Create the API module**

```typescript
import client from './client'

export interface AIPickItem {
  id: number
  code: string
  name: string
  reason: string
  confidence: string | null
  price_at_pick: number | null
  next_day_open: number | null
  next_day_close: number | null
  next_day_change_pct: number | null
  pick_date: string
}

export interface TodayPicksResponse {
  picks: AIPickItem[]
  pick_date: string
  confidence: string | null
}

export interface HistoryGroup {
  pick_date: string
  picks: AIPickItem[]
  count: number
  hit_count: number
  total_backtested: number
  avg_change_pct: number | null
}

export interface PickStats {
  total_dates: number
  total_picks_backtested: number
  hit_count: number
  hit_rate: number
  avg_change_pct: number
  avg_win_pct: number
  avg_loss_pct: number
  today_count: number
}

export function getTodayPicks() {
  return client.get<any, { code: number; message: string; data: TodayPicksResponse }>('/ai-picks/today')
}

export function getPickHistory(page: number = 1, pageSize: number = 20) {
  return client.get<any, { code: number; message: string; data: { items: HistoryGroup[]; total: number; page: number; page_size: number } }>(
    '/ai-picks/history',
    { params: { page, page_size: pageSize } }
  )
}

export function getPickStats() {
  return client.get<any, { code: number; message: string; data: PickStats }>('/ai-picks/stats')
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd "frontend" && npx vue-tsc --noEmit src/api/aiPicks.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/aiPicks.ts
git commit -m "feat: add AI picks frontend API module"
```

---

### Task 6: Create frontend AI recommend view

**Files:**
- Create: `frontend/src/views/AIRecommendView.vue`

- [ ] **Step 1: Create the view component**

```vue
<template>
  <div class="ai-pick-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">🤖 AI 明日推荐</h2>
        <span class="page-subtitle">每日 14:30 AI 基于实时行情自主选股</span>
      </div>
      <div class="page-actions">
        <el-tag v-if="stats.today_count > 0" size="small" effect="dark" round class="count-tag">
          今日 {{ stats.today_count }} 只
        </el-tag>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="refreshAll">
          刷新数据
        </el-button>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="card-icon card-icon--scan">
          <el-icon :size="18"><DataLine /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.total_dates }}</div>
          <div class="summary-label">推荐天数</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon card-icon--score">
          <el-icon :size="18"><TrendCharts /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.hit_rate }}%</div>
          <div class="summary-label">命中率</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon" :class="stats.avg_change_pct >= 0 ? 'card-icon--up' : 'card-icon--down'">
          <el-icon :size="18"><CaretTop v-if="stats.avg_change_pct >= 0" /><CaretBottom v-else /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono" :class="stats.avg_change_pct >= 0 ? 'text-up' : 'text-down'">
            {{ stats.avg_change_pct >= 0 ? '+' : '' }}{{ stats.avg_change_pct }}%
          </div>
          <div class="summary-label">平均收益</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon card-icon--time">
          <el-icon :size="18"><Trophy /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.total_picks_backtested }}</div>
          <div class="summary-label">已回测</div>
        </div>
      </div>
    </div>

    <!-- Today's Picks -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>📊 今日推荐 ({{ todayPickDate || '暂无' }})</span>
          <el-tag v-if="todayConfidence" size="small" effect="plain" :type="confidenceType">
            {{ confidenceLabel }}
          </el-tag>
        </div>
      </template>
      <div v-if="todayPicks.length === 0" class="empty-state">
        <el-empty description="今日暂无推荐数据，请于 14:30 后查看" :image-size="80" />
      </div>
      <div v-else class="pick-list">
        <div v-for="(pick, idx) in todayPicks" :key="pick.id" class="pick-item">
          <div class="pick-rank">#{{ idx + 1 }}</div>
          <div class="pick-info">
            <div class="pick-title">
              <el-link type="primary" :underline="false" @click="goToDetail(pick.code)">
                {{ pick.name }}
              </el-link>
              <span class="pick-code">{{ pick.code }}</span>
              <el-tag v-if="pick.next_day_change_pct != null" size="small" :type="pick.next_day_change_pct > 0 ? 'danger' : 'success'" class="pick-result-tag">
                {{ pick.next_day_change_pct > 0 ? '+' : '' }}{{ pick.next_day_change_pct }}%
              </el-tag>
            </div>
            <div class="pick-reason">{{ pick.reason }}</div>
          </div>
          <el-tag v-if="pick.confidence" size="small" effect="plain" :type="pickConfidenceType(pick.confidence)" class="pick-confidence">
            {{ pickConfidenceLabel(pick.confidence) }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- History Table -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <span>📈 历史战绩</span>
      </template>
      <el-table :data="historyGroups" stripe size="small" v-loading="historyLoading" @row-click="onHistoryRowClick" style="cursor: pointer;">
        <el-table-column prop="pick_date" label="日期" width="120" />
        <el-table-column prop="count" label="推荐数" width="80" align="center" />
        <el-table-column label="命中" width="100" align="center">
          <template #default="{ row }">
            {{ row.hit_count }}/{{ row.total_backtested }}
          </template>
        </el-table-column>
        <el-table-column label="平均涨幅" width="110" align="center">
          <template #default="{ row }">
            <span v-if="row.avg_change_pct != null" :class="row.avg_change_pct >= 0 ? 'text-up' : 'text-down'">
              {{ row.avg_change_pct >= 0 ? '+' : '' }}{{ row.avg_change_pct }}%
            </span>
            <span v-else class="text-dim">-</span>
          </template>
        </el-table-column>
        <el-table-column label="推荐标的" min-width="300">
          <template #default="{ row }">
            <div class="history-picks-inline">
              <span v-for="p in row.picks" :key="p.id" class="history-pick-chip">
                {{ p.name }}
                <template v-if="p.next_day_change_pct != null">
                  <span :class="p.next_day_change_pct >= 0 ? 'text-up' : 'text-down'">
                    ({{ p.next_day_change_pct >= 0 ? '+' : '' }}{{ p.next_day_change_pct }}%)
                  </span>
                </template>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap" v-if="historyTotal > 20">
        <el-pagination
          v-model:current-page="historyPage"
          :page-size="20"
          :total="historyTotal"
          layout="prev, pager, next"
          @current-change="loadHistory"
          background
          size="small"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, DataLine, TrendCharts, Trophy, CaretTop, CaretBottom } from '@element-plus/icons-vue'
import { getTodayPicks, getPickHistory, getPickStats } from '@/api/aiPicks'
import type { AIPickItem, HistoryGroup, PickStats } from '@/api/aiPicks'

const router = useRouter()

const loading = ref(false)
const historyLoading = ref(false)
const todayPicks = ref<AIPickItem[]>([])
const todayPickDate = ref('')
const todayConfidence = ref<string | null>(null)
const historyGroups = ref<HistoryGroup[]>([])
const historyPage = ref(1)
const historyTotal = ref(0)
const stats = ref<PickStats>({
  total_dates: 0,
  total_picks_backtested: 0,
  hit_count: 0,
  hit_rate: 0,
  avg_change_pct: 0,
  avg_win_pct: 0,
  avg_loss_pct: 0,
  today_count: 0,
})

const confidenceType = computed(() => {
  if (todayConfidence.value === 'high') return 'danger'
  if (todayConfidence.value === 'medium') return 'warning'
  return 'info'
})

const confidenceLabel = computed(() => {
  const map: Record<string, string> = { high: '把握较高', medium: '把握中等', low: '把握较低' }
  return map[todayConfidence.value || ''] || todayConfidence.value || ''
})

function pickConfidenceType(c: string) {
  if (c === 'high') return 'danger'
  if (c === 'medium') return 'warning'
  return 'info'
}

function pickConfidenceLabel(c: string) {
  const map: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return map[c] || c
}

function goToDetail(code: string) {
  router.push(`/stocks/${code}`)
}

function onHistoryRowClick(row: HistoryGroup) {
  // Expand: could show picks detail in a dialog, but for now navigate to stock detail
}

async function loadToday() {
  try {
    const res = await getTodayPicks()
    const data = res.data
    todayPicks.value = data.picks || []
    todayPickDate.value = data.pick_date || ''
    todayConfidence.value = data.confidence
  } catch (e) {
    console.error('Failed to load today picks:', e)
  }
}

async function loadHistory(page: number = 1) {
  historyLoading.value = true
  try {
    const res = await getPickHistory(page)
    const data = res.data
    historyGroups.value = data.items || []
    historyTotal.value = data.total
  } catch (e) {
    console.error('Failed to load history:', e)
  } finally {
    historyLoading.value = false
  }
}

async function loadStats() {
  try {
    const res = await getPickStats()
    stats.value = res.data
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

async function refreshAll() {
  loading.value = true
  await Promise.all([loadToday(), loadStats(), loadHistory(historyPage.value)])
  loading.value = false
}

onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.ai-pick-view {
  max-width: 1000px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title-group .page-title {
  margin: 0 0 4px 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 13px;
  color: var(--text-muted);
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.count-tag {
  font-weight: 600;
}

/* Summary Cards (match existing StockRanking style) */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  box-shadow: var(--card-shadow);
  transition: all 0.25s ease;
}

.summary-card:hover {
  box-shadow: var(--card-hover-shadow);
  border-color: rgba(124, 58, 237, 0.15);
}

.card-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(124, 58, 237, 0.08);
  color: #7c3aed;
}

.card-icon--scan { background: rgba(99, 102, 241, 0.08); color: #6366f1; }
.card-icon--score { background: rgba(16, 185, 129, 0.08); color: #10b981; }
.card-icon--up { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.card-icon--down { background: rgba(34, 197, 94, 0.08); color: #22c55e; }
.card-icon--time { background: rgba(245, 158, 11, 0.08); color: #f59e0b; }

.card-body { flex: 1; }

.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.summary-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.section-card {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pick-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.pick-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.pick-item:last-child {
  border-bottom: none;
}

.pick-rank {
  font-size: 18px;
  font-weight: 700;
  color: #7c3aed;
  min-width: 36px;
  line-height: 1.4;
}

.pick-info {
  flex: 1;
  min-width: 0;
}

.pick-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.pick-code {
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'Fira Code', monospace;
}

.pick-result-tag {
  margin-left: 4px;
}

.pick-reason {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.pick-confidence {
  flex-shrink: 0;
  margin-top: 2px;
}

.empty-state {
  padding: 40px 0;
}

.history-picks-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.history-pick-chip {
  font-size: 12px;
  white-space: nowrap;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd "frontend" && npx vue-tsc --noEmit`
Expected: No errors (or only pre-existing errors unrelated to this file).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/AIRecommendView.vue
git commit -m "feat: add AI recommend frontend view with stats, today picks, history"
```

---

### Task 7: Add frontend route and navigation

**Files:**
- Modify: `frontend/src/router/index.ts` (append new route)
- Modify: `frontend/src/App.vue` (append new menu item)

- [ ] **Step 1: Add route**

In `frontend/src/router/index.ts`, after the `/alerts` route (after line 52), add:

```typescript
  {
    path: '/ai-recommend',
    name: 'AIRecommend',
    component: () => import('@/views/AIRecommendView.vue'),
    meta: { title: 'AI明日推荐' },
  },
```

- [ ] **Step 2: Add navigation menu item**

In `frontend/src/App.vue`, after the "智能预警" menu item (after line 76), add:

```html
              <el-menu-item index="/ai-recommend">
                <el-icon><MagicStick /></el-icon>
                <template #title>AI明日推荐</template>
              </el-menu-item>
```

And add `MagicStick` to the icon imports on line 113:

```typescript
import {
  Fold,
  Expand,
  DataAnalysis,
  PieChart,
  List as ListIcon,
  Odometer,
  Setting,
  TrendCharts,
  DataLine,
  Bell,
  MagicStick,
} from '@element-plus/icons-vue'
```

- [ ] **Step 3: Verify frontend builds**

Run: `cd "frontend" && npx vite build`
Expected: Build succeeds without errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.ts frontend/src/App.vue
git commit -m "feat: add AI recommend route and navigation menu item"
```

---

### Task 8: Final verification — end-to-end smoke test

- [ ] **Step 1: Verify backend starts with the new module**

Run: `cd "backend" && python -c "
from app.main import app
from app.models.ai_pick import AIPick
from app.services.ai_pick_service import run_ai_pick_task, collect_market_snapshot
from app.api.ai_picks import router
print('All imports OK')
print(f'Routes: {[r.path for r in router.routes]}')
"`

Expected: `All imports OK` + list of 3 routes.

- [ ] **Step 2: Verify scheduler registers all jobs**

Run: `cd "backend" && python -c "
from app.core.scheduler import register_scheduler, get_scheduler
register_scheduler()
s = get_scheduler()
jobs = [(j.id, j.next_run_time) for j in s.get_jobs()]
for jid, nrt in jobs:
    print(f'  {jid}: next={nrt}')
"`

Expected: Should see `ai_pick`, `ai_pick_backtest_open`, `ai_pick_backtest_close` in the list.

- [ ] **Step 3: Verify frontend dev server starts**

Run: `cd "frontend" && npx vite build --mode development 2>&1 | tail -5`
Expected: Build completes successfully.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final verification and fixes for AI pick feature"
```

---

### File Change Summary

| File | Action | Lines |
|------|--------|-------|
| `backend/app/models/ai_pick.py` | Create | ~30 |
| `backend/app/models/__init__.py` | Modify (+2 lines) | +2 |
| `backend/app/services/ai_pick_service.py` | Create | ~360 |
| `backend/app/api/ai_picks.py` | Create | ~160 |
| `backend/app/core/scheduler.py` | Modify (+24 lines) | +24 |
| `backend/app/main.py` | Modify (+2 lines) | +2 |
| `frontend/src/api/aiPicks.ts` | Create | ~60 |
| `frontend/src/views/AIRecommendView.vue` | Create | ~320 |
| `frontend/src/router/index.ts` | Modify (+6 lines) | +6 |
| `frontend/src/App.vue` | Modify (+4 lines) | +4 |

**Total: ~6 new files, ~4 modified files, ~970 lines of code.**
