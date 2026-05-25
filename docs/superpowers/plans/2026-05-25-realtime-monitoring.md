# Real-Time Monitoring — WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- []`) syntax for tracking.

**Goal:** Replace HTTP polling in the trading view with a WebSocket-based real-time push system for positions, account data, and trade events.

**Architecture:** A centralized `MonitorHub` class manages WebSocket connections and channel subscriptions. Background tasks query the database every 3 seconds and broadcast results to subscribed clients. Trade execution hooks in `trading_service.py` emit instant events on buy/sell. The frontend uses a reconnectable WebSocket client that auto-subscribes to channels and updates the UI reactively.

**Tech Stack:** FastAPI WebSocket, Python asyncio, Vue 3, TypeScript, Element Plus

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/core/websocket.py` | Create | MonitorHub — connection pool, channel routing, broadcaster |
| `backend/app/api/monitor.py` | Create | `/ws/monitor` WebSocket endpoint |
| `backend/app/main.py` | Modify | Register monitor router + start/stop hub in lifespan |
| `backend/app/services/trading_service.py` | Modify | Add `broadcast_trade_event()` calls after execute_buy/execute_sell |
| `frontend/src/types/monitor.ts` | Create | WS message types |
| `frontend/src/utils/websocket.ts` | Create | Reconnectable WebSocket client with channel subscriptions |
| `frontend/src/store/index.ts` | Modify | Add `monitor` store slice |
| `frontend/src/views/TradingView.vue` | Modify | Replace HTTP polling with WS real-time updates |

---

### Task 1: Backend WebSocket Manager

**Files:**
- Create: `backend/app/core/websocket.py`

- [ ] **Step 1: Create MonitorHub class**

```python
"""WebSocket connection manager with channel-based broadcasting."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import WebSocket
from loguru import logger


class MonitorHub:
    """Manages WebSocket connections and broadcasts messages by channel."""

    def __init__(self) -> None:
        # conn_id -> {ws, channels: set[str]}
        self._connections: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._broadcast_task: asyncio.Task | None = None

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> str:
        """Accept a new WebSocket connection. Returns connection ID."""
        await ws.accept()
        conn_id = uuid.uuid4().hex[:12]
        async with self._lock:
            self._connections[conn_id] = {"ws": ws, "channels": set()}
        logger.info(f"WS connected: {conn_id} (total={len(self._connections)})")
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        """Remove a connection."""
        async with self._lock:
            self._connections.pop(conn_id, None)
        logger.info(f"WS disconnected: {conn_id} (total={len(self._connections)})")

    async def subscribe(self, conn_id: str, channels: list[str]) -> None:
        """Subscribe a connection to channels."""
        async with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                entry["channels"].update(channels)

    async def unsubscribe(self, conn_id: str, channels: list[str]) -> None:
        """Unsubscribe a connection from channels."""
        async with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                entry["channels"].difference_update(channels)

    async def broadcast(self, channel: str, data: Any) -> None:
        """Send a message to all connections subscribed to a channel."""
        msg = json.dumps(
            {"channel": channel, "data": data, "ts": datetime.now().isoformat()},
            default=str,
        )
        dead: list[str] = []
        async with self._lock:
            for conn_id, entry in self._connections.items():
                if channel in entry["channels"]:
                    try:
                        await entry["ws"].send_text(msg)
                    except Exception:
                        dead.append(conn_id)
        for conn_id in dead:
            await self.disconnect(conn_id)

    async def _handle_message(self, conn_id: str, raw: str) -> None:
        """Process an incoming client message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        action = msg.get("action")
        channels = msg.get("channels", [])
        if action == "subscribe":
            await self.subscribe(conn_id, channels)
        elif action == "unsubscribe":
            await self.unsubscribe(conn_id, channels)
        elif action == "ping":
            await self.broadcast_to_conn(conn_id, "system", {"type": "pong"})

    async def broadcast_to_conn(self, conn_id: str, channel: str, data: Any) -> None:
        """Send a message to a specific connection."""
        msg = json.dumps({"channel": channel, "data": data, "ts": datetime.now().isoformat()}, default=str)
        async with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                try:
                    await entry["ws"].send_text(msg)
                except Exception:
                    pass

    async def handle_ws(self, ws: WebSocket) -> None:
        """Main handler loop for a single WebSocket connection."""
        conn_id = await self.connect(ws)
        try:
            while True:
                raw = await ws.receive_text()
                await self._handle_message(conn_id, raw)
        except Exception:
            pass
        finally:
            await self.disconnect(conn_id)


# Singleton instance
monitor_hub = MonitorHub()
```

- [ ] **Step 2: Verify file is syntactically correct**

Run: `cd /Users/lxxxx/Desktop/shares/backend && python -c "import ast; ast.parse(open('app/core/websocket.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Backend WebSocket API Endpoint

**Files:**
- Create: `backend/app/api/monitor.py`

- [ ] **Step 1: Create the WebSocket endpoint**

```python
"""WebSocket monitoring endpoint."""

from fastapi import APIRouter, WebSocket

from app.core.websocket import monitor_hub

router = APIRouter()


@router.websocket("/ws/monitor")
async def ws_monitor(ws: WebSocket):
    """WebSocket endpoint for real-time monitoring.

    Client sends: {"action": "subscribe", "channels": ["positions", "account", "trades"]}
    Server pushes: {"channel": "positions", "data": [...], "ts": "2026-05-25T10:30:00"}
    """
    await monitor_hub.handle_ws(ws)
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/lxxxx/Desktop/shares/backend && python -c "from app.api.monitor import router; print('OK')"`
Expected: `OK`

---

### Task 3: Register WebSocket Route and Start Hub in Lifespan

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Import the monitor router**

Change line 10 from:
```python
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading
```
to:
```python
from app.api import health, stocks, factors, ranking, strategy, sectors, backtest, trading, monitor
```

- [ ] **Step 2: Include the monitor router**

After line 76 (`app.include_router(trading.router, prefix="/api")`), add:
```python
app.include_router(monitor.router, prefix="/api")
```

- [ ] **Step 3: Start broadcast task in lifespan**

In the `lifespan` function, after `register_scheduler()` (line 21), add:
```python
    # Start WebSocket broadcast loop
    from app.core.websocket import monitor_hub
    monitor_hub.start_broadcast_loop()
```

And before `shutdown_scheduler()` (line 48), add:
```python
        from app.core.websocket import monitor_hub
        monitor_hub.stop_broadcast_loop()
```

- [ ] **Step 4: Add start/stop methods to MonitorHub**

In `backend/app/core/websocket.py`, add these methods to the `MonitorHub` class (after the `handle_ws` method):

```python
    def start_broadcast_loop(self) -> None:
        """Start the background broadcast loop (call from lifespan)."""
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            logger.info("MonitorHub broadcast loop started")

    def stop_broadcast_loop(self) -> None:
        """Stop the background broadcast loop."""
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            logger.info("MonitorHub broadcast loop stopped")

    async def _broadcast_loop(self) -> None:
        """Periodically broadcast account + positions to subscribers."""
        while True:
            try:
                if self._connections:
                    await self._push_trading_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcast loop error: {e}")
            await asyncio.sleep(3)

    async def _push_trading_data(self) -> None:
        """Query DB and push positions/account data."""
        from app.core.database import AsyncSessionLocal
        from app.services.trading_service import (
            get_or_create_account,
            get_positions_with_prices,
            update_account_value,
        )

        async with AsyncSessionLocal() as session:
            account = await get_or_create_account(session)
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
```

- [ ] **Step 5: Verify the app loads**

Run: `cd /Users/lxxxx/Desktop/shares/backend && python -c "from app.main import app; print('App loaded OK')"`
Expected: `App loaded OK`

---

### Task 4: Add Trade Event Broadcasting to trading_service.py

**Files:**
- Modify: `backend/app/services/trading_service.py`

- [ ] **Step 1: Add broadcast helper function**

Add this function at the top of the file, after the imports (around line 15):

```python
def _broadcast_trade_event(action: str, code: str, name: str, price: float, shares: int, pnl: float | None = None, reason: str = "") -> None:
    """Fire-and-forget broadcast of a trade event to WebSocket clients."""
    import asyncio
    from app.core.websocket import monitor_hub

    data = {
        "action": action,
        "code": code,
        "name": name,
        "price": price,
        "shares": shares,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(monitor_hub.broadcast("trades", data))
    except RuntimeError:
        pass
```

- [ ] **Step 2: Call broadcast in `execute_buy`**

In `execute_buy()`, after line 170 (`logger.info(f"BUY ...")`), add:
```python
    _broadcast_trade_event("buy", code, name, price, shares, reason=log.reason)
```

- [ ] **Step 3: Call broadcast in `execute_sell`**

In `execute_sell()`, after line 210 (`logger.info(f"SELL ...")`), add:
```python
    _broadcast_trade_event(action, position.code, position.name, price, sell_shares, pnl=pnl, reason=reason)
```

- [ ] **Step 4: Verify no import errors**

Run: `cd /Users/lxxxx/Desktop/shares/backend && python -c "from app.services.trading_service import execute_buy, execute_sell; print('OK')"`
Expected: `OK`

---

### Task 5: Frontend WebSocket Types

**Files:**
- Create: `frontend/src/types/monitor.ts`

- [ ] **Step 1: Create type definitions**

```typescript
// WebSocket message types for real-time monitoring

export interface WSMessage<T = unknown> {
  channel: string
  data: T
  ts: string
}

export interface WSSubscribeMessage {
  action: 'subscribe' | 'unsubscribe'
  channels: string[]
}

export interface WSTradeEvent {
  action: 'buy' | 'sell' | 'stop_loss' | 'take_profit'
  code: string
  name: string
  price: number
  shares: number
  pnl: number | null
  reason: string
  timestamp: string
}

export type WSChannel = 'positions' | 'account' | 'trades' | 'market' | 'system' | 'alerts'

export type WSMessageHandler = (data: unknown) => void
```

---

### Task 6: Frontend WebSocket Client

**Files:**
- Create: `frontend/src/utils/websocket.ts`

- [ ] **Step 1: Create the reconnectable WebSocket client**

```typescript
import type { WSChannel, WSMessage, WSMessageHandler, WSSubscribeMessage } from '@/types/monitor'

type ConnectionState = 'connecting' | 'connected' | 'disconnected'

class MonitorWebSocket {
  private ws: WebSocket | null = null
  private url: string
  private channels = new Set<WSChannel>()
  private handlers = new Map<string, Set<WSMessageHandler>>()
  private lifecycleHandlers = new Map<string, Set<() => void>>()
  private reconnectAttempts = 0
  private maxReconnectDelay = 30000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pingTimer: ReturnType<typeof setInterval> | null = null

  state: ConnectionState = 'disconnected'

  constructor() {
    // Derive WS URL from current page location or API base
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    this.url = `${protocol}//${host}/api/ws/monitor`
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.state = 'connecting'
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      this.state = 'connected'
      this.reconnectAttempts = 0
      // Re-subscribe to all channels
      if (this.channels.size > 0) {
        this._send({ action: 'subscribe', channels: [...this.channels] })
      }
      // Start heartbeat
      this.pingTimer = setInterval(() => {
        this._send({ action: 'ping' })
      }, 30000)
      this._emitLifecycle('open')
    }

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        const channelHandlers = this.handlers.get(msg.channel)
        if (channelHandlers) {
          for (const handler of channelHandlers) {
            handler(msg.data)
          }
        }
      } catch { /* ignore parse errors */ }
    }

    this.ws.onclose = () => {
      this.state = 'disconnected'
      if (this.pingTimer) clearInterval(this.pingTimer)
      this._emitLifecycle('close')
      this._scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.pingTimer) clearInterval(this.pingTimer)
    this.ws?.close()
    this.ws = null
    this.state = 'disconnected'
  }

  subscribe(channels: WSChannel[]) {
    for (const ch of channels) this.channels.add(ch)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this._send({ action: 'subscribe', channels })
    }
  }

  unsubscribe(channels: WSChannel[]) {
    for (const ch of channels) this.channels.delete(ch)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this._send({ action: 'unsubscribe', channels })
    }
  }

  on(event: string, handler: WSMessageHandler | (() => void)) {
    if (event === 'open' || event === 'close') {
      if (!this.lifecycleHandlers.has(event)) {
        this.lifecycleHandlers.set(event, new Set())
      }
      this.lifecycleHandlers.get(event)!.add(handler as () => void)
    } else {
      if (!this.handlers.has(event)) {
        this.handlers.set(event, new Set())
      }
      this.handlers.get(event)!.add(handler as WSMessageHandler)
    }
  }

  off(event: string, handler: WSMessageHandler | (() => void)) {
    if (event === 'open' || event === 'close') {
      this.lifecycleHandlers.get(event)?.delete(handler as () => void)
    } else {
      this.handlers.get(event)?.delete(handler as WSMessageHandler)
    }
  }

  private _emitLifecycle(event: string) {
    this.lifecycleHandlers.get(event)?.forEach((fn) => fn())
  }

  private _send(msg: WSSubscribeMessage | { action: 'ping' }) {
    this.ws?.send(JSON.stringify(msg))
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, this.maxReconnectDelay)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}

export const monitorWs = new MonitorWebSocket()
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /Users/lxxxx/Desktop/shares/frontend && npx vue-tsc --noEmit 2>&1 | head -20`
Expected: No errors related to new files

---

### Task 7: Update Pinia Store with Monitor State

**Files:**
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Add monitor store**

Add a new store after the existing `useStocksStore`:

```typescript
export const useMonitorStore = defineStore('monitor', () => {
  const wsConnected = ref(false)
  const positions = ref<Record<string, unknown>[]>([])
  const account = reactive({
    initial_capital: 500000,
    cash: 500000,
    total_value: 500000,
    position_value: 0,
    pnl: 0,
    pnl_pct: 0,
    is_active: false,
  })
  const recentTrades = ref<Record<string, unknown>[]>([])

  function setWsConnected(state: boolean) {
    wsConnected.value = state
  }

  function updatePositions(data: Record<string, unknown>[]) {
    positions.value = data
  }

  function updateAccount(data: Record<string, unknown>) {
    Object.assign(account, data)
  }

  function addTrade(data: Record<string, unknown>) {
    recentTrades.value.unshift(data)
    if (recentTrades.value.length > 50) {
      recentTrades.value = recentTrades.value.slice(0, 50)
    }
  }

  return {
    wsConnected, positions, account, recentTrades,
    setWsConnected, updatePositions, updateAccount, addTrade,
  }
})
```

---

### Task 8: Update TradingView.vue to Use WebSocket

**Files:**
- Modify: `frontend/src/views/TradingView.vue`

- [ ] **Step 1: Replace the script section**

Replace the entire `<script lang="ts" setup>` block with:

```typescript
<script lang="ts" setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import {
  getTradingLogs,
  startTradingBot,
  stopTradingBot,
  resetTradingAccount,
} from '@/api/trading'
import { monitorWs } from '@/utils/websocket'
import { useMonitorStore } from '@/store'

const monitor = useMonitorStore()

const actionLoading = ref(false)
const logsLoading = ref(false)
const logsPage = ref(1)
const logsTotal = ref(0)

// Use store state for reactive account/positions
const account = monitor.account
const positions = monitor.positions
const tradeLogs = ref<Record<string, unknown>[]>([])

function formatMoney(val: number): string {
  if (val == null) return '--'
  return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(str: string): string {
  if (!str) return '--'
  return str.replace('T', ' ').substring(0, 19)
}

function actionLabel(action: string): string {
  const map: Record<string, string> = { buy: '买入', sell: '卖出', stop_loss: '止损', take_profit: '止盈' }
  return map[action] || action
}

function actionTagType(action: string): string {
  const map: Record<string, string> = { buy: 'danger', sell: 'success', stop_loss: 'warning', take_profit: 'primary' }
  return map[action] || ''
}

async function loadLogs() {
  logsLoading.value = true
  try {
    const { data } = await getTradingLogs(logsPage.value, 20)
    tradeLogs.value = data?.items || []
    logsTotal.value = data?.total || 0
  } catch { tradeLogs.value = [] }
  finally { logsLoading.value = false }
}

function handleWsTrade(data: unknown) {
  const trade = data as Record<string, unknown>
  monitor.addTrade(trade)
  // Reload logs to show the new trade
  loadLogs()
}

async function handleStart() {
  actionLoading.value = true
  try {
    await startTradingBot()
    ElMessage.success('交易机器人已启动')
  } catch { ElMessage.error('启动失败') }
  finally { actionLoading.value = false }
}

async function handleStop() {
  actionLoading.value = true
  try {
    await stopTradingBot()
    ElMessage.success('交易机器人已停止')
  } catch { ElMessage.error('停止失败') }
  finally { actionLoading.value = false }
}

async function handleReset() {
  try {
    await ElMessageBox.confirm('确定要重置模拟账户吗？所有持仓和交易记录将被清除。', '确认重置', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  actionLoading.value = true
  try {
    await resetTradingAccount()
    ElMessage.success('账户已重置')
    loadLogs()
  } catch { ElMessage.error('重置失败') }
  finally { actionLoading.value = false }
}

onMounted(() => {
  // Connect WebSocket and subscribe to trading channels
  monitorWs.on('open', () => monitor.setWsConnected(true))
  monitorWs.on('close', () => monitor.setWsConnected(false))
  monitorWs.connect()
  monitorWs.subscribe(['positions', 'account', 'trades'])
  monitorWs.on('positions', (data) => monitor.updatePositions(data as Record<string, unknown>[]))
  monitorWs.on('account', (data) => monitor.updateAccount(data as Record<string, unknown>))
  monitorWs.on('trades', handleWsTrade)

  // Load trade logs via HTTP (paginated, no need for WS)
  loadLogs()
})

onBeforeUnmount(() => {
  monitorWs.off('positions', (data) => monitor.updatePositions(data as Record<string, unknown>[]))
  monitorWs.off('account', (data) => monitor.updateAccount(data as Record<string, unknown>))
  monitorWs.off('trades', handleWsTrade)
  monitorWs.unsubscribe(['positions', 'account', 'trades'])
})
</script>
```

- [ ] **Step 2: Add connection status indicator to the template**

In the template, inside the `<div class="page-header">` section, add between the title and actions:

```html
      <div class="ws-status">
        <span class="status-dot" :class="monitor.wsConnected ? 'connected' : 'disconnected'" />
        <span class="status-text">{{ monitor.wsConnected ? '实时连接' : '连接中...' }}</span>
      </div>
```

- [ ] **Step 3: Add status indicator styles**

In the `<style scoped>` section, add:

```css
.ws-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transition: background-color 0.3s ease;
}

.status-dot.connected {
  background-color: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
}

.status-dot.disconnected {
  background-color: #f59e0b;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
```

- [ ] **Step 4: Remove the old HTTP auto-refresh timer**

The old code had `startAutoRefresh()` with `setInterval` — that's already removed in the new script. Verify the template still renders correctly.

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd /Users/lxxxx/Desktop/shares/frontend && npx vue-tsc --noEmit 2>&1 | head -30`
Expected: No errors

---

### Task 9: Add Monitor Store Export Verification

**Files:**
- Verify: `frontend/src/store/index.ts`

- [ ] **Step 1: Check both stores are exported**

Run: `cd /Users/lxxxx/Desktop/shares/frontend && grep -c "export const use" src/store/index.ts`
Expected: `2` (useStocksStore and useMonitorStore)

---

### Task 10: End-to-End Verification

- [ ] **Step 1: Start the backend**

Run: `cd /Users/lxxxx/Desktop/shares/backend && python -m app.main &`
Wait for the server to start (look for "Uvicorn running" in output).

- [ ] **Step 2: Verify WebSocket endpoint is reachable**

Run: `cd /Users/lxxxx/Desktop/shares && python -c "
import asyncio
import websockets
async def test():
    async with websockets.connect('ws://localhost:8000/api/ws/monitor') as ws:
        import json
        await ws.send(json.dumps({'action': 'subscribe', 'channels': ['account']}))
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(msg)
        assert data['channel'] == 'account'
        assert 'data' in data
        print(f'Received: channel={data[\"channel\"]} keys={list(data[\"data\"].keys())}')
asyncio.run(test())
"`
Expected: `Received: channel=account keys=[...]`

- [ ] **Step 3: Start the frontend**

Run: `cd /Users/lxxxx/Desktop/shares/frontend && npm run dev &`

- [ ] **Step 4: Open the trading page and verify**

Open `http://localhost:5173/trading` in a browser. Verify:
- Connection status indicator shows green "实时连接"
- Account cards show data without manual refresh
- Positions table populates
- Trade logs load via HTTP

---

### Self-Review Checklist

- [ ] Spec coverage: WebSocket manager, endpoint, trading hooks, frontend client, TradingView integration — all covered
- [ ] No placeholders: All code blocks are complete, no TBD/TODO
- [ ] Type consistency: WSMessage, WSChannel, handler types all match between frontend files
- [ ] Single-server assumption is documented and sufficient for current deployment
