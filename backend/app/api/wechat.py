"""WeChat Work callback endpoint for interactive bot."""

import asyncio
import json

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from loguru import logger

from app.core.config import settings
from app.services.wechat_bot import (
    _decrypt_message,
    handle_command,
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
    computed_sign = verify_signature(settings.wechat_token, timestamp, nonce, echostr)
    if computed_sign != msg_signature:
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

    # Body is JSON: {"encrypt": "..."}
    try:
        data = json.loads(body)
        encrypt = data.get("encrypt", "")
    except (json.JSONDecodeError, AttributeError):
        logger.warning(f"Unexpected callback body: {body[:200]}")
        return PlainTextResponse("")

    if not encrypt:
        logger.warning("No encrypt field in callback body")
        return PlainTextResponse("")

    # Decrypt — result is JSON for AI bot
    try:
        decrypted = _decrypt_message(encrypt)
        msg = json.loads(decrypted)
    except Exception as exc:
        logger.error(f"Decrypt/parse failed: {exc}")
        return PlainTextResponse("")

    # Only handle text messages
    if msg.get("msgtype") != "text":
        return PlainTextResponse("")

    # Extract text — AI bot puts text in "text.content"
    text_data = msg.get("text", {})
    content = text_data.get("content", "").strip()
    from_user = msg.get("from", {}).get("userid", "")

    if not content or not from_user:
        return PlainTextResponse("")

    # The content may include @mention prefix, strip it
    if content.startswith("@"):
        parts = content.split(" ", 1)
        content = parts[1].strip() if len(parts) > 1 else ""

    if not content:
        return PlainTextResponse("")

    logger.info(f"WeChat bot received: {content} from {from_user}")

    # Process and reply in background
    asyncio.create_task(_process_and_reply(msg, content))

    return PlainTextResponse("")


async def _process_and_reply(msg: dict, content: str):
    """Process command and reply via response_url."""
    response_url = msg.get("response_url", "")
    try:
        reply = await handle_command(content)
        await _reply_via_url(response_url, reply)
    except Exception as exc:
        logger.error(f"Bot command failed: {exc}")
        try:
            await _reply_via_url(response_url, "处理请求时出错，请稍后重试")
        except Exception:
            pass


async def _reply_via_url(response_url: str, content: str):
    """Reply to AI bot via response_url."""
    if not response_url:
        logger.warning("No response_url, cannot reply")
        return

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(response_url, json=payload, timeout=10.0)
        if resp.status_code != 200:
            logger.warning(f"Reply failed: {resp.status_code} {resp.text[:200]}")
        else:
            logger.debug(f"Reply sent to {response_url[:50]}")
