# WeChat Work Interactive Bot Design

## Overview

Add an interactive WeChat Work bot that responds to @mentions in group chats with stock quotes, factor scores, and AI analysis. Uses WeChat Work custom app (自建应用) with callback URL for receiving messages and app API for sending replies.

## Architecture

```
Group @mention → WeChat Work server → POST /api/wechat/callback (AES-encrypted XML)
→ Decrypt → Parse command → Query data → Reply via app message API
```

## Commands

| Input | Response | Latency |
|-------|----------|---------|
| `@bot 000001` | Quote + factor scores + ranking | <2s |
| `@bot 000001 分析` | AI deep analysis (DeepSeek) | 3-10s |
| `@bot 平安银行` | Fuzzy match stock name → same as code | <2s |
| `@bot 帮助` | Usage instructions | instant |

## Response Format

**Quote + Scores:**
```
📈 平安银行 (000001)
当前价: 11.52  涨跌: +2.34%  成交量: 1.2亿
---
因子评分: 78.5 (排名 #3)
  技术面: 82.1  基本面: 75.3  情绪面: 76.8
---
发送 "000001 分析" 获取 AI 深度点评
```

**AI Analysis:**
```
🤖 AI 点评 - 平安银行

平安银行近期技术面表现强劲，MACD 金叉信号明确...
综合评分 78.5，排名第3。
```

## Files

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/api/wechat.py` | Create | Callback endpoint + signature verification |
| `backend/app/services/wechat_bot.py` | Create | Message decrypt, command parsing, reply building |
| `backend/app/core/config.py` | Modify | Add WeChat Work app config fields |
| `backend/app/main.py` | Modify | Register wechat router |

## Implementation Details

### Callback Endpoint (`api/wechat.py`)

- `GET /api/wechat/callback` — Verification endpoint (WeChat Work calls this once during setup)
  - Verify `msg_signature` using Token + timestamp + nonce + echostr
  - Return decrypted `echostr`

- `POST /api/wechat/callback` — Message receiver
  - Parse XML body: `ToUserName`, `FromUserName`, `CreateTime`, `MsgType`, `Content`, `MsgId`
  - Verify `msg_signature`
  - If `MsgType == "text"`, extract `Content`, route to command handler
  - Return HTTP 200 (actual reply sent asynchronously via app API)

### Message Flow (`services/wechat_bot.py`)

1. **Decrypt**: AES-128-CBC with `EncodingAESKey`, verify SHA1 signature
2. **Parse command**: Extract stock code (6-digit) or stock name from `Content`
3. **Route**:
   - "帮助" → return help text
   - 6-digit code → lookup quote + scores
   - other text → fuzzy match stock name from DB, then same as code
   - code + "分析" → trigger AI analysis
4. **Reply**: POST to `https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=TOKEN`
   - Message type: `markdown` (企业微信应用支持 markdown)
   - Target: `touser` (the user who sent the message)

### Config (`core/config.py`)

New settings (from `.env`):
- `WECHAT_CORP_ID` — Enterprise ID
- `WECHAT_APP_AGENT_ID` — App AgentId
- `WECHAT_APP_SECRET` — App Secret
- `WECHAT_TOKEN` — Callback verification Token
- `WECHAT_ENCODING_AES_KEY` — Callback AES key (43 chars)

### Data Sources

- **Real-time quote**: Reuse existing `refresh_live_prices` (Tencent) or Sina API
- **Factor scores**: Query `StockRanking` table (latest date)
- **Factor details**: Query `FactorValue` table grouped by type
- **AI analysis**: Reuse `ai_report_service.generate_report` (DeepSeek)
- **Stock name lookup**: Query `StockInfo` table for fuzzy match

## Prerequisites (User)

1. Enterprise WeChat admin console: create custom app
2. Set callback URL to `https://your-domain/api/wechat/callback`
3. Configure Token and EncodingAESKey in admin console
4. Set `.env` variables: `WECHAT_CORP_ID`, `WECHAT_APP_AGENT_ID`, `WECHAT_APP_SECRET`, `WECHAT_TOKEN`, `WECHAT_ENCODING_AES_KEY`
5. Server must have public IP or reverse proxy (nginx)
