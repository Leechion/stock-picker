"""Notification service - sends ranking alerts to messaging platforms."""

import httpx
from datetime import date
from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.stock import StockDaily, StockInfo
from app.services.ranking_service import get_ranking_list
from app.services.ai_report_service import generate_report

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

# 主要指数 Eastmoney secid
INDEX_SECIDS = {
    "上证指数": "1.000001",
    "深证成指": "0.399001",
    "创业板指": "0.399006",
}


def fetch_market_indices() -> list[dict]:
    """Fetch major index prices using AKShare."""
    import akshare as ak

    index_symbols = {
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "创业板指": "sz399006",
    }
    results = []
    for name, symbol in index_symbols.items():
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is not None and len(df) >= 2:
                last = df.iloc[-1]
                prev = df.iloc[-2]
                close = float(last["close"])
                prev_close = float(prev["close"])
                change_pct = (close / prev_close - 1) * 100 if prev_close > 0 else 0
                results.append({
                    "name": name,
                    "price": close,
                    "change_pct": round(change_pct, 2),
                })
        except Exception as exc:
            logger.debug(f"Failed to fetch {name}: {exc}")
    if results:
        logger.info(f"Fetched {len(results)} index prices")
    return results


async def fetch_price_alerts(trading_date: date) -> dict:
    """Fetch stocks with significant price changes.

    Returns dict with: limit_up, limit_down, big_up (>5%), big_down (<-5%).
    Uses the latest available data date if trading_date has no data.
    """
    from sqlalchemy import func

    async with AsyncSessionLocal() as session:
        # Find the latest date with data (may not be trading_date)
        latest_stmt = select(func.max(StockDaily.trade_date)).where(
            StockDaily.trade_date <= trading_date
        )
        latest_result = await session.execute(latest_stmt)
        actual_date = latest_result.scalar_one_or_none()

        if actual_date is None:
            return {"limit_up": [], "limit_down": [], "big_up": [], "big_down": [],
                    "total_limit_up": 0, "total_limit_down": 0}

        stmt = (
            select(StockDaily.code, StockDaily.change_pct, StockInfo.name)
            .join(StockInfo, StockDaily.code == StockInfo.code)
            .where(StockDaily.trade_date == actual_date)
        )
        result = await session.execute(stmt)
        rows = result.all()

    limit_up, limit_down, big_up, big_down = [], [], [], []
    for code, change_pct, name in rows:
        if change_pct is None:
            continue
        label = f"{code} {name}" if name else code
        if change_pct >= 9.9:
            limit_up.append(label)
        elif change_pct <= -9.9:
            limit_down.append(label)
        elif change_pct >= 5.0:
            big_up.append(label)
        elif change_pct <= -5.0:
            big_down.append(label)

    return {
        "date": str(actual_date),
        "limit_up": limit_up[:10],
        "limit_down": limit_down[:10],
        "big_up": big_up[:10],
        "big_down": big_down[:10],
        "total_limit_up": len(limit_up),
        "total_limit_down": len(limit_down),
    }


def format_index_section(indices: list[dict]) -> str:
    """Format market indices into markdown."""
    if not indices:
        return ""
    lines = ["## 📈 大盘指数", ""]
    for idx in indices:
        pct = idx["change_pct"]
        arrow = "🔴" if pct < 0 else "🟢"
        lines.append(f"{arrow} **{idx['name']}** {idx['price']:.2f}  ({pct:+.2f}%)")
    lines.append("")
    return "\n".join(lines)


def format_alert_section(alerts: dict) -> str:
    """Format price alerts into markdown."""
    lines = []
    has_content = False

    if alerts["limit_up"]:
        has_content = True
        lines.append(f"**🔴 涨停 ({alerts['total_limit_up']}只)**：{'、'.join(alerts['limit_up'][:5])}")
    if alerts["limit_down"]:
        has_content = True
        lines.append(f"**🟢 跌停 ({alerts['total_limit_down']}只)**：{'、'.join(alerts['limit_down'][:5])}")
    if alerts["big_up"]:
        has_content = True
        lines.append(f"**📈 大涨 >5%** ({len(alerts['big_up'])}只)：{'、'.join(alerts['big_up'][:5])}")
    if alerts["big_down"]:
        has_content = True
        lines.append(f"**📉 大跌 <-5%** ({len(alerts['big_down'])}只)：{'、'.join(alerts['big_down'][:5])}")

    if not has_content:
        return ""

    return "## ⚠️ 异动提醒\n\n" + "\n".join(lines) + "\n"


def format_ranking_message(records: list[dict], trading_date: date, ai_text: str = "") -> str:
    """Format top rankings into a WeChat Work markdown message."""
    lines = [
        f"## 📊 今日选股排名 Top {len(records)}",
        f"> {trading_date}\n",
    ]
    for r in records:
        name = r.get("name", "")
        label = f"{r['code']} {name}" if name else r["code"]
        lines.append(f"**{r['rank']}. {label}** — 总分 **{r['score']}**")
        parts = []
        if r.get("tech_score") is not None:
            parts.append(f"技术 {r['tech_score']:.1f}")
        if r.get("fund_score") is not None:
            parts.append(f"基本面 {r['fund_score']:.1f}")
        if r.get("sent_score") is not None:
            parts.append(f"情绪 {r['sent_score']:.1f}")
        if parts:
            lines.append(f"  {' | '.join(parts)}")
        lines.append("")

    if ai_text:
        lines.append("---")
        lines.append("**AI 点评：**")
        lines.append(ai_text)
        lines.append("")

    lines.append("---")
    lines.append("*数据来源: StockPicker | 自动生成*")
    return "\n".join(lines)


def send_wechat_work(webhook_url: str, content: str) -> bool:
    """Send a markdown message to a WeChat Work group robot webhook."""
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("WeChat Work notification sent successfully")
            return True
        logger.error(f"WeChat Work API error: {data}")
        return False
    except Exception as exc:
        logger.error(f"Failed to send WeChat Work notification: {exc}")
        return False


async def send_daily_notification(trading_date: date | None = None) -> bool:
    """Fetch top rankings, indices, alerts and push to configured channels."""
    if not settings.wechat_webhook_url:
        logger.debug("No webhook URL configured, skipping notification")
        return False

    if trading_date is None:
        trading_date = date.today()

    async with AsyncSessionLocal() as session:
        records, total = await get_ranking_list(
            session, trading_date, page=1, page_size=settings.notification_top_n
        )

    if not records:
        logger.warning(f"No rankings found for {trading_date}, skipping notification")
        return False

    # Build message sections
    indices = fetch_market_indices()
    alerts = await fetch_price_alerts(trading_date)
    ai_text = generate_report(records)

    # Compose full message: indices → alerts → rankings → AI
    sections = []
    index_section = format_index_section(indices)
    if index_section:
        sections.append(index_section)

    alert_section = format_alert_section(alerts)
    if alert_section:
        sections.append(alert_section)

    sections.append(format_ranking_message(records, trading_date, ai_text))

    message = "\n".join(sections)
    return send_wechat_work(settings.wechat_webhook_url, message)
