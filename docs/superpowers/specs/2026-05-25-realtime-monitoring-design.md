# Real-Time Monitoring System Design

## Overview

Add a WebSocket-based real-time monitoring system to the A-share quantitative trading platform. The system replaces HTTP polling with server-push WebSocket connections, enabling live updates for trading data, market overview, system health, and alerts.

## Architecture

```
Frontend (Vue 3)                          Backend (FastAPI)
┌──────────────────┐                    ┌──────────────────────┐
│ WebSocket Client │──── ws:// ────────▶│  /ws/monitor         │
│                  │                    │                      │
│ subscribe:       │◀─── JSON msgs ────│  MonitorHub          │
│  positions       │                    │   ├─ ConnectionPool  │
│  account         │                    │   ├─ ChannelRouter   │
│  trades          │                    │   └─ Broadcaster     │
│  market          │                    │       │              │
│  system          │                    │  BackgroundTasks:    │
│  alerts          │                    │   ├─ 3s: trading push│
└──────────────────┘                    │   ├─ 10s: market     │
                                        │   └─ 30s: system     │
                                        └──────────────────────┘
```

## Phases

### Phase 1: Trading Panel Real-Time Push

**Backend:**
- `backend/app/core/websocket.py` — MonitorHub class
  - Manages WebSocket connections with channel subscriptions
  - Dict-based connection pool: `{conn_id: {ws, channels: set}}`
  - Background tasks: query DB every 3s → broadcast to `positions`/`account` subscribers
  - Trade event hook: trading_service calls `monitor_hub.broadcast("trades", data)` on buy/sell/stop-loss
  - Heartbeat ping/pong every 30s to detect dead connections
  - No Redis dependency for Phase 1 (in-memory only, single-server assumption)
- `backend/app/api/monitor.py` — `/ws/monitor` WebSocket endpoint
  - Client sends: `{"action": "subscribe", "channels": ["positions", "account"]}`
  - Server pushes: `{"channel": "positions", "data": [...], "ts": "2026-05-25T10:30:00"}`
- Modify `trading_service.py` — add `monitor_hub.broadcast()` calls after trade execution

**Frontend:**
- `frontend/src/utils/websocket.ts` — ReconnectableWebSocket class
  - Auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
  - Heartbeat detection (send ping, expect pong within 5s)
  - Channel subscription management
  - TypeScript typed: `subscribe(channels: string[])`, `onMessage(channel, callback)`
- `frontend/src/types/monitor.ts` — WS message types
- Modify `TradingView.vue` — replace `setInterval(fetchPositions)` with WS `onMessage("positions", ...)`
- Modify `frontend/src/store/index.ts` — add `monitor` store slice for WS state

### Phase 2: Market Monitoring Dashboard

- MonitorHub new channel: `market`
- Push every 10s: index prices (SH/SZ/ChiNext), sector fund flow Top10, limit-up/down counts
- New view: `MonitorDashboard.vue` — ECharts real-time charts
- New route: `/monitor` in router

### Phase 3: System Health Monitoring

- MonitorHub new channel: `system`
- Push every 30s: scheduler job status, data source latency, last sync time, active connections
- Extend `MonitorDashboard.vue` with system health panel

### Phase 4: Alert System

- New alert rule engine: configurable thresholds for price, change%, P&L, factor scores
- MonitorHub new channel: `alerts`
- Real-time push on rule trigger + notification integration
- Alert management UI for CRUD operations

## Files to Create/Modify

| File | Action | Phase |
|------|--------|-------|
| `backend/app/core/websocket.py` | Create | 1 |
| `backend/app/api/monitor.py` | Create | 1 |
| `backend/app/main.py` | Modify (register WS route) | 1 |
| `backend/app/services/trading_service.py` | Modify (broadcast hooks) | 1 |
| `backend/app/core/scheduler.py` | Modify (WS broadcast tasks) | 1 |
| `frontend/src/utils/websocket.ts` | Create | 1 |
| `frontend/src/types/monitor.ts` | Create | 1 |
| `frontend/src/store/index.ts` | Modify (monitor slice) | 1 |
| `frontend/src/views/TradingView.vue` | Modify (WS integration) | 1 |
| `frontend/src/views/MonitorDashboard.vue` | Create | 2 |
| `frontend/src/router/index.ts` | Modify | 2 |

## Data Format

```typescript
// Client → Server
interface SubscribeMessage {
  action: "subscribe" | "unsubscribe";
  channels: ("positions" | "account" | "trades" | "market" | "system" | "alerts")[];
}

// Server → Client
interface PushMessage {
  channel: string;
  data: any;
  ts: string; // ISO timestamp
}
```

## Assumptions

- Single server deployment (no multi-instance needed)
- Redis available but not required for Phase 1 (in-memory state sufficient)
- Existing trading_service and data providers remain unchanged in API
- Frontend Element Plus + ECharts stack continues for new views
