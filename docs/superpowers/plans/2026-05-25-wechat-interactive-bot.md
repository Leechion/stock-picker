# WeChat Interactive Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive WeChat Work bot that receives @mentions in group chats and replies with stock quotes, factor scores, and AI analysis.

**Architecture:** A callback endpoint receives encrypted messages from WeChat Work, decrypts them, parses commands (stock code/name), queries real-time quotes and DB scores, and replies via the app message API. AI analysis uses the existing DeepSeek integration.

**Tech Stack:** FastAPI, httpx, WeChat Work callback API (AES-128-CBC), DeepSeek LLM

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/core/config.py` | Modify | Add 4 WeChat Work app config fields |
| `backend/app/services/wechat_bot.py` | Create | Decrypt, parse, query, build reply |
| `backend/app/api/wechat.py` | Create | Callback GET/POST endpoints |
| `backend/app/main.py` | Modify | Register wechat router |

---

### Task 1: Add WeChat Work App Config

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add config fields**

Add after line 28 (`deepseek_model: str = "deepseek-chat"`):

```python
    wechat_corp_id: str = ""
    wechat_app_agent_id: int = 0
    wechat_app_secret: str = ""
    wechat_token: str = ""
    wechat_encoding_aes_key: str = ""
```

- [ ] **Step 2: Verify settings load**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "from app.core.config import settings; print(f'corp_id={settings.wechat_corp_id}, token={settings.wechat_token}')"`
Expected: `corp_id=, token=` (empty defaults are fine)

---

### Task 2: Create WeChat Bot Service

**Files:**
- Create: `backend/app/services/wechat_bot.py`

- [ ] **Step 1: Create the full service**

```python
"""WeChat Work interactive bot - decrypt messages, parse commands, reply."""

from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET
from datetime import date

from loguru import logger

from app.core.config import settings


# ===== AES Decryption =====

def _decrypt_message(encrypted: str) -> str:
    """Decrypt WeChat Work callback message (AES-128-CBC)."""
    from Cryptodome.Cipher import AES

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


def verify_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> bool:
    """Verify msg_signature from WeChat Work callback."""
    import hashlib
    parts = sorted([token, timestamp, nonce, encrypted])
    sign = hashlib.sha1("".join(parts).encode()).hexdigest()
    return sign


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
    """Fetch real-time quote for a stock code. Returns dict with price/change/volume."""
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

    async with AsyncSessionLocal() as session:
        # Find latest ranking date
        latest_date_stmt = select(func.max(StockRanking.rank_date))
        latest_date = (await session.execute(latest_date_stmt)).scalar_one_or_none()
        if not latest_date:
            return None

        stmt = select(StockRanking).where(
            StockRanking.code == code,
            StockRanking.rank_date == latest_date,
            StockRanking.strategy == "default",
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
      000001 → quote + scores
      000001 分析 → AI analysis
      平安银行 → fuzzy match name → quote + scores
    """
    text = content.strip()

    if text in ("帮助", "help", "使用说明"):
        return (
            "📋 **StockPicker Bot 使用说明**\n\n"
            "发送以下指令：\n"
            "- `000001` — 查看行情 + 因子评分\n"
            "- `000001 分析` — 获取 AI 深度分析\n"
            "- `平安银行` — 按股票名称查询\n"
            "- `帮助` — 显示本帮助"
        )

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
        return f"未找到股票: {text}\n发送 "帮助" 查看使用说明"

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
```

- [ ] **Step 2: Verify the module imports**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "from app.services.wechat_bot import handle_command, send_reply, parse_callback_xml; print('OK')"`
Expected: `OK`

---

### Task 3: Create WeChat Callback Endpoint

**Files:**
- Create: `backend/app/api/wechat.py`

- [ ] **Step 1: Create the router**

```python
"""WeChat Work callback endpoint for interactive bot."""

import hashlib
from urllib.parse import unquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from loguru import logger

from app.core.config import settings
from app.services.wechat_bot import (
    _decrypt_message,
    handle_command,
    parse_callback_xml,
    send_reply,
    verify_signature,
)

router = APIRouter()


@router.get("/wechat/callback")
async def wechat_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """Verification endpoint — WeChat Work calls this once during setup."""
    sign = verify_signature(settings.wechat_token, timestamp, nonce, echostr)
    if sign != msg_signature:
        logger.warning("WeChat callback signature mismatch")
        return PlainTextResponse("Invalid signature", status_code=403)

    try:
        decrypted = _decrypt_message(echostr)
        return PlainTextResponse(decrypted)
    except Exception as exc:
        logger.error(f"Decryption failed: {exc}")
        return PlainTextResponse("Decryption error", status_code=500)


@router.post("/wechat/callback")
async def wechat_callback(request: Request):
    """Message receiver — handles @mentions from group chats."""
    body = (await request.body()).decode("utf-8")

    # Parse XML
    msg = parse_callback_xml(body)
    if not msg:
        return PlainTextResponse("")

    # Decrypt content if encrypted
    encrypt = msg.get("encrypt", "")
    if encrypt:
        try:
            decrypted_xml = _decrypt_message(encrypt)
            msg = parse_callback_xml(decrypted_xml)
            if not msg:
                return PlainTextResponse("")
        except Exception as exc:
            logger.error(f"Decrypt failed: {exc}")
            return PlainTextResponse("")

    # Only handle text messages
    if msg.get("msg_type") != "text":
        return PlainTextResponse("")

    content = msg.get("content", "").strip()
    from_user = msg.get("from_user", "")

    if not content or not from_user:
        return PlainTextResponse("")

    logger.info(f"WeChat bot received: {content} from {from_user}")

    # Handle command and reply asynchronously
    import asyncio
    asyncio.create_task(_process_and_reply(from_user, content))

    # Return empty response immediately (WeChat expects 200 within 5s)
    return PlainTextResponse("")


async def _process_and_reply(from_user: str, content: str):
    """Process command and send reply (runs in background)."""
    try:
        reply = await handle_command(content)
        await send_reply(from_user, reply)
    except Exception as exc:
        logger.error(f"Bot command failed: {exc}")
        try:
            await send_reply(from_user, "处理请求时出错，请稍后重试")
        except Exception:
            pass
```

- [ ] **Step 2: Verify the router loads**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "from app.api.wechat import router; print('OK')"`
Expected: `OK`

---

### Task 4: Register WeChat Route in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add wechat to the import**

Change line 10 from:
```python
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor
```
to:
```python
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor, wechat
```

- [ ] **Step 2: Include the router**

After line 82 (`app.include_router(monitor.router, prefix="/api")`), add:
```python
app.include_router(wechat.router, prefix="/api")
```

- [ ] **Step 3: Verify app loads**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "from app.main import app; routes = [r.path for r in app.routes]; assert '/api/wechat/callback' in routes; print('OK')"`
Expected: `OK`

---

### Task 5: End-to-End Verification

- [ ] **Step 1: Verify all modules import correctly**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "
from app.main import app
from app.services.wechat_bot import handle_command, send_reply, parse_callback_xml, _decrypt_message
routes = [r.path for r in app.routes]
assert '/api/wechat/callback' in routes
print(f'Routes with wechat: {[r for r in routes if \"wechat\" in r]}')
print('All OK')
"`

Expected output:
```
Routes with wechat: ['/api/wechat/callback', '/api/wechat/callback']
All OK
```

- [ ] **Step 2: Test command parsing (no network)**

Run: `cd /Users/lxxxx/Desktop/shares/backend && .venv/bin/python -c "
import asyncio
from app.services.wechat_bot import handle_command

async def test():
    result = await handle_command('帮助')
    assert 'StockPicker' in result
    print(f'帮助 response length: {len(result)}')
    print('OK')
asyncio.run(test())
"`

Expected: `帮助 response length: 120+` / `OK`

---

## Self-Review Checklist

- [ ] Spec coverage: callback endpoint, message decryption, command parsing, quote/score/AI queries, reply via app API — all covered
- [ ] No placeholders: All code is complete, no TBD/TODO
- [ ] Type consistency: `handle_command` returns `str`, `send_reply` returns `bool`, `parse_callback_xml` returns `dict | None`
- [ ] Error handling: All external calls wrapped in try/except
- [ ] WeChat 5s timeout: Callback returns 200 immediately, reply sent via background task
