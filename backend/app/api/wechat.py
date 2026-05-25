"""WeChat Work callback endpoint for interactive bot."""

import asyncio

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

    # Process and reply in background (WeChat expects response within 5s)
    asyncio.create_task(_process_and_reply(from_user, content))

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
