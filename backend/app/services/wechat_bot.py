"""WeChat Work interactive bot - decrypt messages, parse commands, reply."""

from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET
import asyncio
from datetime import date

from loguru import logger

from app.core.config import settings


# ===== AES Decryption =====

def _decrypt_message(encrypted: str) -> str:
    """Decrypt WeChat Work callback message (AES-128-CBC)."""
    from Crypto.Cipher import AES

    key = base64.b64decode(settings.wechat_encoding_aes_key + "=")
    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(base64.b64decode(encrypted))

    # Remove PKCS7 padding
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]

    # Skip 16-byte random + 4-byte network-byte-order msg_len
    msg_len = struct.unpack(">I", decrypted[16:20])[0]
    return decrypted[20:20 + msg_len].decode("utf-8")


def verify_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    """Compute SHA1 signature for WeChat Work callback verification."""
    parts = sorted([token, timestamp, nonce, encrypted])
    return hashlib.sha1("".join(parts).encode()).hexdigest()


def parse_callback_xml(body: str) -> dict | None:
    """Parse incoming XML from WeChat Work callback.

    Returns dict with: to_user, from_user, create_time, msg_type, content, msg_id.
    """
    try:
        root = ET.fromstring(body)
        return {
            "to_user": root.findtext("ToUserName", ""),
            "from_user": root.findtext("FromUserName", ""),
            "create_time": root.findtext("CreateTime", ""),
            "msg_type": root.findtext("MsgType", ""),
            "content": root.findtext("Content", ""),
            "msg_id": root.findtext("MsgId", ""),
            "encrypt": root.findtext("Encrypt", ""),
        }
    except ET.ParseError:
        logger.warning("Failed to parse callback XML")
        return None


# ===== Stock Query =====

async def _get_realtime_quote(code: str) -> dict | None:
    """Fetch real-time quote for a stock code via Tencent finance API."""
    import httpx

    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        url = f"http://qt.gtimg.cn/q={prefix}{code}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0)
            text = resp.content.decode("gbk", errors="replace")
        line = text.strip().split(";")[0]
        if "=" not in line:
            return None
        fields = line.split("~")
        if len(fields) < 4:
            return None
        return {
            "code": fields[2],
            "name": fields[1],
            "price": float(fields[3]) if fields[3] else 0,
            "prev_close": float(fields[4]) if fields[4] else 0,
            "open": float(fields[5]) if fields[5] else 0,
            "volume": float(fields[6]) if fields[6] else 0,
            "amount": float(fields[37]) if len(fields) > 37 and fields[37] else 0,
            "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] else 0,
            "high": float(fields[33]) if len(fields) > 33 and fields[33] else 0,
            "low": float(fields[34]) if len(fields) > 34 and fields[34] else 0,
        }
    except Exception as exc:
        logger.debug(f"Failed to fetch quote for {code}: {exc}")
        return None


async def _get_stock_scores(code: str) -> dict | None:
    """Get latest factor scores and ranking for a stock."""
    from sqlalchemy import func, select
    from app.core.database import AsyncSessionLocal
    from app.models.stock import StockRanking
    from app.services.strategy_loader import strategy_loader

    async with AsyncSessionLocal() as session:
        latest_date_stmt = select(func.max(StockRanking.rank_date))
        latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
        if not latest_date:
            return None

        stmt = select(StockRanking).where(
            StockRanking.code == code,
            StockRanking.rank_date == latest_date,
            StockRanking.strategy == strategy_loader.active_name,
        )
        result = await session.execute(stmt)
        ranking = result.scalar_one_or_none()
        if not ranking:
            return None

        return {
            "rank": ranking.rank_position,
            "total_score": round(ranking.total_score, 1),
            "tech_score": round(ranking.tech_score, 1),
            "fund_score": round(ranking.fund_score, 1),
            "sent_score": round(ranking.sent_score, 1),
            "industry": ranking.industry or "",
            "rank_date": str(latest_date),
        }


async def _get_latest_ranking_date() -> date | None:
    """Get the latest date that has ranking data."""
    from sqlalchemy import func, select
    from app.core.database import AsyncSessionLocal
    from app.models.stock import StockRanking

    async with AsyncSessionLocal() as session:
        stmt = select(func.max(StockRanking.rank_date))
        return (await session.execute(stmt)).scalar_one_or_none()


def _generate_batch_analysis(records: list[dict]) -> str:
    """Generate AI batch analysis for top stocks (synchronous)."""
    from app.services.ai_report_service import generate_report

    try:
        return generate_report(records)
    except Exception as exc:
        logger.error(f"Batch AI analysis failed: {exc}")
        return ""


async def _cmd_recommend() -> str:
    """推荐: Top 10 rankings + AI analysis."""
    ranking_date = await _get_latest_ranking_date()
    if not ranking_date:
        return "暂无排名数据，请稍后再试"

    from app.core.database import AsyncSessionLocal
    from app.services.ranking_service import get_ranking_list

    async with AsyncSessionLocal() as session:
        records, _ = await get_ranking_list(session, ranking_date, page=1, page_size=10)

    if not records:
        return f"暂无排名数据 ({ranking_date})，请稍后再试"

    lines = [f"🏆 **今日 Top 10 推荐** ({ranking_date})\n"]
    for i, r in enumerate(records, 1):
        lines.append(f"{i}. **{r['name']}** ({r['code']}) — 综合 {r['score']}")

    # AI batch analysis (run in thread pool since it's sync)
    loop = asyncio.get_running_loop()
    ai_text = await loop.run_in_executor(None, _generate_batch_analysis, records)
    if ai_text:
        lines.append("---")
        lines.append(f"🤖 **AI 综合点评**\n{ai_text}")

    return "\n".join(lines)


async def _cmd_sector_heat() -> str:
    """板块: Sector heat rankings."""
    from app.services import sector_service

    loop = asyncio.get_running_loop()
    sectors = await loop.run_in_executor(None, sector_service.fetch_sector_performance)
    if not sectors:
        return "无法获取板块数据，请稍后再试"

    heat = await loop.run_in_executor(None, sector_service.compute_sector_heat, sectors)
    # Sort by heat score descending, top 5
    sorted_sectors = sorted(heat.items(), key=lambda x: x[1], reverse=True)[:5]

    # Also get real-time change pct for context
    perf_map = {s["name"]: s for s in sectors}

    lines = ["🔥 **板块热度 Top 5**\n"]
    for i, (name, score) in enumerate(sorted_sectors, 1):
        pct = perf_map.get(name, {}).get("change_pct", 0)
        arrow = "🔴" if pct >= 0 else "🟢"
        lines.append(f"{i}. **{name}** — 热度 {score:.1f}  {arrow} {pct:+.2f}%")

    lines.append("\n发送行业名称查看该行业排名前5的股票")
    return "\n".join(lines)


async def _cmd_strategy_switch(name: str) -> str:
    """动量/价值/均衡: Switch active strategy."""
    from app.services.strategy_loader import strategy_loader

    # Map Chinese names to slugs
    slug_map = {"均衡": "default", "动量": "momentum", "价值": "value"}
    slug = slug_map.get(name, name)

    if strategy_loader.set_active(slug):
        config = strategy_loader.get_active_config()
        display_name = config.get("name", slug)
        return f"✅ 策略已切换为：**{display_name}**"
    else:
        available = ", ".join(s["slug"] for s in strategy_loader.list_strategies())
        return f"❌ 未找到策略「{name}」\n可用策略: {available}"


async def _cmd_strategy_view() -> str:
    """策略: View current strategy and available strategies."""
    from app.services.strategy_loader import strategy_loader

    strategies = strategy_loader.list_strategies()
    active = strategy_loader.active_name

    lines = ["⚙️ **当前策略配置**\n"]
    for s in strategies:
        marker = "👉" if s["slug"] == active else "  "
        lines.append(f"{marker} **{s['name']}** — {s['description']}")

    lines.append("\n发送「均衡/动量/价值」切换策略")
    return "\n".join(lines)


async def _cmd_industry_query(industry: str) -> str:
    """<行业名>: Industry top 5 stocks."""
    ranking_date = await _get_latest_ranking_date()
    if not ranking_date:
        return "暂无排名数据，请稍后再试"

    from app.core.database import AsyncSessionLocal
    from app.services.ranking_service import get_sector_stocks

    async with AsyncSessionLocal() as session:
        records, total = await get_sector_stocks(session, industry, ranking_date, page=1, page_size=5)

    if not records:
        # Try fuzzy match via sector rankings
        from app.services.ranking_service import get_sector_rankings
        async with AsyncSessionLocal() as session:
            sectors = await get_sector_rankings(session, ranking_date)
        matched = [s for s in sectors if industry in s["industry"]]
        if matched:
            return f"未找到行业「{industry}」，你是不是想找：{', '.join(s['industry'] for s in matched[:3])}"
        return f"未找到行业「{industry}」的相关数据"

    lines = [f"📊 **{industry}** 行业 Top 5 ({ranking_date})\n"]
    for i, r in enumerate(records, 1):
        lines.append(f"{i}. **{r['name']}** ({r['code']}) — 综合 {r['score']}")

    if total > 5:
        lines.append(f"\n共 {total} 只股票，发送「{industry} 更多」查看完整排名")

    return "\n".join(lines)


async def _find_stock_by_name(name: str) -> str | None:
    """Fuzzy match stock name, return code."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.stock import StockInfo

    async with AsyncSessionLocal() as session:
        stmt = select(StockInfo.code).where(StockInfo.name.contains(name)).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _generate_stock_analysis(code: str, name: str, quote: dict, scores: dict) -> str:
    """Generate AI analysis for a single stock using DeepSeek."""
    import httpx

    if not settings.deepseek_api_key:
        return "AI 分析功能未配置 (缺少 DeepSeek API Key)"

    prompt = (
        f"请对以下A股做一段简短分析（200字以内），口语化，指出亮点和风险：\n"
        f"股票：{name} ({code})\n"
        f"当前价：{quote['price']}，涨跌：{quote['change_pct']}%\n"
        f"因子评分：总分{scores['total_score']}（排名#{scores['rank']}），"
        f"技术{scores['tech_score']}，基本面{scores['fund_score']}，情绪{scores['sent_score']}"
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.deepseek_base_url}/v1/chat/completions",
                json={
                    "model": settings.deepseek_model,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的A股量化分析师，擅长用通俗语言解读数据。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error(f"AI analysis failed for {code}: {exc}")
        return "AI 分析生成失败，请稍后重试"


# ===== Command Handling =====

async def handle_command(content: str) -> str:
    """Parse command text and return reply markdown.

    Supported:
      帮助 → help text
      推荐 → Top 10 rankings + AI analysis
      板块 → sector heat rankings
      动量/价值/均衡 → switch strategy
      策略 → view current strategy
      000001 → quote + scores
      000001 分析 → AI analysis
      平安银行 → fuzzy match name → quote + scores
      <行业名> → industry top 5 stocks
    """
    text = content.strip()

    if text in ("帮助", "help", "使用说明"):
        return (
            "📋 **StockPicker Bot 使用说明**\n\n"
            "📊 **选股推荐**\n"
            "- `推荐` — 今日 Top 10 推荐 + AI 点评\n"
            "- `板块` — 板块热度排名 Top 5\n"
            "- `均衡/动量/价值` — 切换选股策略\n"
            "- `策略` — 查看当前策略\n"
            "\n📈 **个股查询**\n"
            "- `000001` — 查看行情 + 因子评分\n"
            "- `000001 分析` — 获取 AI 深度分析\n"
            "- `平安银行` — 按股票名称查询\n"
            "\n🏭 **行业查询**\n"
            "- 发送行业名（如「半导体」）— 行业排名前5"
        )

    # New commands
    if text == "推荐":
        return await _cmd_recommend()

    if text == "板块":
        return await _cmd_sector_heat()

    if text in ("动量", "价值", "均衡"):
        return await _cmd_strategy_switch(text)

    if text == "策略":
        return await _cmd_strategy_view()

    # Check for "分析" suffix
    want_analysis = text.endswith("分析")
    if want_analysis:
        text = text[:-2].strip()

    # Try to extract 6-digit stock code
    code = None
    if text.isdigit() and len(text) == 6:
        code = text
    else:
        # Fuzzy match by name
        code = await _find_stock_by_name(text)

    if not code:
        # Try as industry name
        return await _cmd_industry_query(text)

    # Fetch quote
    quote = await _get_realtime_quote(code)
    if not quote:
        return f"无法获取 {code} 的实时行情，请检查代码是否正确"

    # Fetch scores
    scores = await _get_stock_scores(code)

    # Build quote reply
    name = quote["name"]
    pct = quote["change_pct"]
    arrow = "🔴" if pct >= 0 else "🟢"
    lines = [
        f"📈 **{name}** ({code})",
        f"当前价: {quote['price']}  {arrow} {pct:+.2f}%",
        f"成交量: {quote['volume']/10000:.0f}万手  成交额: {quote['amount']/100000000:.2f}亿",
    ]

    if scores:
        lines.append("---")
        lines.append(f"因子评分: **{scores['total_score']}** (排名 #{scores['rank']})")
        lines.append(f"  技术面: {scores['tech_score']}  基本面: {scores['fund_score']}  情绪面: {scores['sent_score']}")

    if not want_analysis:
        lines.append("---")
        lines.append(f'发送 "{code} 分析" 获取 AI 深度点评')
        return "\n".join(lines)

    # Generate AI analysis
    lines.append("---")
    lines.append("🤖 **AI 点评**\n")
    analysis = await _generate_stock_analysis(code, name, quote, scores)
    lines.append(analysis)
    return "\n".join(lines)


# ===== Reply via App API =====

async def send_reply(to_user: str, content: str) -> bool:
    """Send a reply to a user via WeChat Work app message API."""
    import httpx

    if not settings.wechat_corp_id or not settings.wechat_app_secret:
        logger.warning("WeChat Work app not configured, skipping reply")
        return False

    # Get access_token
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={
                    "corpid": settings.wechat_corp_id,
                    "corpsecret": settings.wechat_app_secret,
                },
                timeout=10.0,
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logger.error(f"Failed to get access_token: {token_data}")
                return False
    except Exception as exc:
        logger.error(f"Token request failed: {exc}")
        return False

    # Send message
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
                json={
                    "touser": to_user,
                    "msgtype": "markdown",
                    "agentid": settings.wechat_app_agent_id,
                    "markdown": {"content": content},
                },
                timeout=10.0,
            )
            data = resp.json()
            if data.get("errcode") == 0:
                logger.info(f"Reply sent to {to_user}")
                return True
            logger.error(f"Send reply failed: {data}")
            return False
    except Exception as exc:
        logger.error(f"Send reply request failed: {exc}")
        return False
