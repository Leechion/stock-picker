"""AI report service - generates natural language stock analysis via LLM."""

import httpx
from loguru import logger

from app.core.config import settings


def _build_prompt(records: list[dict]) -> str:
    """Build the prompt for AI analysis of top-ranked stocks."""
    lines = [
        "你是一个专业的A股量化分析师。请根据以下股票的量化评分数据，生成一份简明扼要的每日选股分析报告。",
        "",
        "要求：",
        "1. 每只股票用1-2句话点评，指出亮点和风险",
        "2. 重点关注基本面和技术面的配合",
        "3. 用口语化、通俗易懂的中文",
        "4. 控制在300字以内",
        "",
        "今日排名数据：",
    ]
    for r in records:
        name = r.get("name", "")
        label = f"{r['code']} {name}" if name else r["code"]
        lines.append(
            f"- {label}: 总分{r['score']}, "
            f"技术{r.get('tech_score', 'N/A')}, "
            f"基本面{r.get('fund_score', 'N/A')}, "
            f"情绪{r.get('sent_score', 'N/A')}"
        )
    return "\n".join(lines)


def generate_report(records: list[dict]) -> str:
    """Call DeepSeek API to generate an analysis report.

    Returns the AI-generated text, or a fallback message on failure.
    """
    if not settings.deepseek_api_key:
        return ""

    prompt = _build_prompt(records)
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": "你是一个专业的A股量化分析师，擅长用通俗语言解读量化数据。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 800,
    }
    try:
        resp = httpx.post(
            f"{settings.deepseek_base_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        logger.info("AI report generated successfully")
        return content
    except Exception as exc:
        logger.error(f"AI report generation failed: {exc}")
        return ""
