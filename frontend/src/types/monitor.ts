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

export type WSChannel = 'positions' | 'account' | 'trades' | 'market' | 'system' | 'alerts' | 'sync_progress'

export type WSMessageHandler = (data: unknown) => void
