"""Monitor API — WebSocket endpoint for real-time trading data."""

from fastapi import APIRouter, WebSocket

from app.core.websocket import monitor_hub

router = APIRouter()


@router.websocket("/ws/monitor")
async def monitor_ws(ws: WebSocket):
    await monitor_hub.handle_ws(ws)
