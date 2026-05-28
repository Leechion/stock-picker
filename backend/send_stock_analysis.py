"""Generate DeepSeek AI analysis for 合锻智能 (603011) and send to WeChat group."""
import asyncio
import sys
sys.path.insert(0, ".")

from app.services.notification_service import send_wechat_work
from app.core.config import settings


async def get_realtime_quote(code: str) -> dict | None:
    import httpx
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
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


async def get_stock_scores(code: str) -> dict | None:
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
            "total_count": None,  # not available on StockRanking model
        }


async def generate_stock_analysis(code: str, name: str, quote: dict, scores: dict | None) -> str:
    import httpx

    prompt_lines = [
        "请对以下A股做一段专业分析（300字左右），口语化但不失深度，指出核心亮点和风险：",
        f"股票：{name} ({code})",
        f"当前价：{quote['price']}，涨跌幅：{quote['change_pct']}%",
        f"今日开盘：{quote['open']}，最高：{quote['high']}，最低：{quote['low']}",
        f"成交量：{quote['volume']/10000:.0f}万手  成交额：{quote['amount']/100000000:.2f}亿",
    ]
    if scores:
        prompt_lines.extend([
            f"因子评分：综合总分{scores['total_score']}（共{scores['total_count']}只股票中排名#{scores['rank']}）",
            f"技术面{scores['tech_score']} | 基本面{scores['fund_score']} | 情绪面{scores['sent_score']}",
            f"所属行业：{scores['industry']}",
        ])
    prompt_lines.append("请给出投资建议和风险提示。")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.deepseek_base_url}/v1/chat/completions",
                json={
                    "model": settings.deepseek_model,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的A股量化分析师，擅长从数据出发给出客观、有洞察的分析。使用通俗语言。每次分析结尾加上风险提示。"},
                        {"role": "user", "content": "\n".join(prompt_lines)},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 600,
                },
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"AI 分析生成失败: {exc}"


def format_analysis_message(code: str, quote: dict, scores: dict | None, ai_text: str) -> str:
    name = quote["name"]
    pct = quote["change_pct"]
    arrow = "🔴" if pct >= 0 else "🟢"

    lines = [
        f"🤖 **AI 个股深度分析**",
        "",
        f"## 📈 {name} ({code})",
        f"当前价: **{quote['price']}**  {arrow} {pct:+.2f}%",
        f"今开: {quote['open']}  |  最高: {quote['high']}  |  最低: {quote['low']}",
        f"成交量: {quote['volume']/10000:.0f}万手  |  成交额: {quote['amount']/100000000:.2f}亿",
    ]

    if scores:
        lines.append("")
        rank_info = f"排名 #{scores['rank']}"
        if scores.get("total_count"):
            rank_info += f"/{scores['total_count']}"
        lines.append(f"**因子评分**  ({rank_info})")
        lines.append(f"综合: {scores['total_score']}  |  技术: {scores['tech_score']}  |  基本面: {scores['fund_score']}  |  情绪: {scores['sent_score']}")
        lines.append(f"行业: {scores['industry']}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(ai_text)
    lines.append("")
    lines.append("---")
    lines.append(f"📅 数据日期: {scores['rank_date'] if scores else 'N/A'}  |  StockPicker AI 分析")

    return "\n".join(lines)


async def main():
    code = "603011"

    print("Fetching real-time quote...")
    quote = await get_realtime_quote(code)
    if not quote:
        print(f"Failed to get real-time quote for {code}")
        return
    print(f"  {quote['name']} 当前价: {quote['price']} 涨跌: {quote['change_pct']}%")

    print("Fetching factor scores...")
    scores = await get_stock_scores(code)
    if scores:
        print(f"  综合评分: {scores['total_score']} 排名 #{scores['rank']}/{scores['total_count']}")
    else:
        print("  No scores available in database")

    print("Generating AI analysis via DeepSeek...")
    ai_text = await generate_stock_analysis(code, quote["name"], quote, scores)
    print(f"  AI Response:\n{ai_text}")

    print("Sending to WeChat group...")
    message = format_analysis_message(code, quote, scores, ai_text)
    success = send_wechat_work(settings.wechat_webhook_url, message)
    if success:
        print("✅ Sent successfully!")
    else:
        print("❌ Failed to send to WeChat group")


if __name__ == "__main__":
    asyncio.run(main())
