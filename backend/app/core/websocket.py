"""WebSocket connection manager (MonitorHub) for real-time trading data."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.services.trading_service import (
    get_or_create_account,
    get_positions_with_prices,
    update_account_value,
)


class MonitorHub:
    """Manages WebSocket connections and broadcasts trading data."""

    def __init__(self) -> None:
        # {conn_id: {"ws": WebSocket, "channels": set[str]}}
        self._connections: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._broadcast_task: asyncio.Task | None = None

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
            except Exception:
                dead.append(conn_id)
        for conn_id in dead:
            await self.disconnect(conn_id)

    # ------------------------------------------------------------------
    # Main WS handler
    # ------------------------------------------------------------------

    async def handle_ws(self, ws: WebSocket) -> None:
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
                    except Exception:
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
        async with AsyncSessionLocal() as session:
            account = await get_or_create_account(session)
            if not account.is_active:
                return
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
