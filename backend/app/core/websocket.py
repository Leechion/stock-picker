"""WebSocket connection manager (MonitorHub) for real-time trading data."""

from __future__ import annotations

import asyncio
import hmac
import json
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.trading_service import (
    get_account,
    get_positions_with_prices,
    update_account_value,
)


# WebSocket close code 1008 = policy violation (used for rejected auth).
WS_CLOSE_POLICY_VIOLATION = 1008


def _extract_ws_token(ws: WebSocket) -> str:
    """Pull a candidate token from the query string or request headers."""
    # Query string: ?token=xxx
    try:
        query = parse_qs(ws.url.query or "")
        values = query.get("token") or query.get("access_token") or []
        if values and values[0]:
            return values[0]
    except Exception as e:  # pragma: no cover - defensive, malformed URL
        logger.debug(f"WS token query parse failed: {e}")

    # Headers: Authorization: Bearer xxx  /  X-WS-Token: xxx
    headers = ws.headers
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (headers.get("x-ws-token") or "").strip()


def authorize_ws(ws: WebSocket) -> tuple[bool, str]:
    """Validate an incoming WebSocket handshake.

    Returns ``(ok, reason)``. When ``settings.ws_auth_enabled`` is False this is
    a no-op and always allows the connection, preserving the behaviour of
    existing deployments.
    """
    if not settings.ws_auth_enabled:
        return True, "auth disabled"

    # 1. Origin allow-list (only enforced when configured and present)
    allowed_origins = settings.ws_allowed_origins or []
    origin = (ws.headers.get("origin") or "").strip()
    if allowed_origins and origin and origin not in allowed_origins:
        return False, f"origin not allowed: {origin}"
    if allowed_origins and not origin:
        logger.debug("WS handshake without Origin header; origin check skipped")

    # 2. Shared-secret token
    expected = settings.ws_auth_token or ""
    if not expected:
        # Enabled but no token configured: fail closed only if an origin list
        # was also configured, otherwise there is nothing to verify against.
        if allowed_origins:
            return True, "origin-only check"
        return False, "ws_auth_enabled but no ws_auth_token configured"

    provided = _extract_ws_token(ws)
    if not provided:
        return False, "missing token"
    if not hmac.compare_digest(provided, expected):
        return False, "invalid token"
    return True, "ok"


class MonitorHub:
    """Manages WebSocket connections and broadcasts trading data."""

    def __init__(self) -> None:
        # {conn_id: {"ws": WebSocket, "channels": set[str]}}
        self._connections: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._broadcast_task: asyncio.Task | None = None
        self._cached_is_active: bool = False
        self._cache_valid_at: float = 0
        self._cache_ttl: float = 5.0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        conn_id = uuid.uuid4().hex[:12]
        async with self._lock:
            self._connections[conn_id] = {"ws": ws, "channels": set()}
            logger.info(f"WS connected: {conn_id} (total={len(self._connections)})")
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        async with self._lock:
            self._connections.pop(conn_id, None)
            logger.info(f"WS disconnected: {conn_id} (total={len(self._connections)})")

    # ------------------------------------------------------------------
    # Channel subscription
    # ------------------------------------------------------------------

    async def subscribe(self, conn_id: str, channels: list[str]) -> None:
        async with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                entry["channels"].update(channels)

    async def unsubscribe(self, conn_id: str, channels: list[str]) -> None:
        async with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                entry["channels"].difference_update(channels)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, channel: str, data: Any) -> None:
        message = json.dumps(
            {"channel": channel, "data": data, "ts": datetime.now().isoformat()},
            ensure_ascii=False,
            default=str,
        )
        async with self._lock:
            items = list(self._connections.items())
        dead: list[str] = []
        for conn_id, entry in items:
            if channel not in entry["channels"]:
                continue
            try:
                await entry["ws"].send_text(message)
            except Exception as e:
                # Send failure usually means the client is gone; drop it below
                # but keep the broadcast loop alive for the healthy peers.
                logger.debug(f"WS broadcast to {conn_id} failed, dropping connection: {e}")
                dead.append(conn_id)
        for conn_id in dead:
            await self.disconnect(conn_id)

    # ------------------------------------------------------------------
    # Main WS handler
    # ------------------------------------------------------------------

    async def handle_ws(self, ws: WebSocket) -> None:
        # Optional auth: reject before accept() so unauthenticated peers never
        # join the hub. No-op when settings.ws_auth_enabled is False.
        try:
            ok, reason = authorize_ws(ws)
        except Exception as e:
            logger.exception(f"WS authorization check failed: {e}")
            ok, reason = (not settings.ws_auth_enabled), "auth check error"

        if not ok:
            logger.warning(f"WS connection rejected: {reason} (client={ws.client})")
            try:
                await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason=reason[:100])
            except Exception as e:
                logger.debug(f"WS close after rejection failed: {e}")
            return

        conn_id = await self.connect(ws)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"WS {conn_id}: invalid JSON: {raw[:120]}")
                    continue

                action = msg.get("action")
                if action == "subscribe":
                    channels = msg.get("channels", [])
                    if isinstance(channels, list):
                        await self.subscribe(conn_id, channels)
                elif action == "unsubscribe":
                    channels = msg.get("channels", [])
                    if isinstance(channels, list):
                        await self.unsubscribe(conn_id, channels)
                elif action == "ping":
                    try:
                        await ws.send_text(json.dumps({"action": "pong"}))
                    except Exception as e:
                        # Client vanished mid-ping: log then drop the loop.
                        logger.debug(f"WS {conn_id}: pong send failed, closing: {e}")
                        break
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception(f"WS error for {conn_id}")
        finally:
            await self.disconnect(conn_id)

    # ------------------------------------------------------------------
    # Background broadcast loop
    # ------------------------------------------------------------------

    def start_broadcast_loop(self) -> None:
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            logger.info("WS broadcast loop started")

    async def stop_broadcast_loop(self) -> None:
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
            self._broadcast_task = None
            logger.info("WS broadcast loop stopped")

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                await self._push_trading_data()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in WS broadcast loop")
            await asyncio.sleep(3)

    async def _push_trading_data(self) -> None:
        if not self._connections:
            return
        # Skip DB query if trading is not active (cache check)
        if not self._cached_is_active:
            now = time.monotonic()
            if now - self._cache_valid_at < 10:
                return
        async with AsyncSessionLocal() as session:
            account = await get_account(session)
            if account is None or not account.is_active:
                self._cached_is_active = False
                self._cache_valid_at = time.monotonic()
                return
            self._cached_is_active = True
            self._cache_valid_at = time.monotonic()
            positions = await get_positions_with_prices(session, account.id)
            value_info = await update_account_value(session, account)
            await session.commit()

            await self.broadcast("positions", positions)
            await self.broadcast("account", {
                "id": account.id,
                "initial_capital": account.initial_capital,
                "cash": round(account.cash, 2),
                "total_value": round(account.total_value, 2),
                "is_active": account.is_active,
                **value_info,
            })


# Singleton
monitor_hub = MonitorHub()
