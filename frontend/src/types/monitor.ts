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

export type WSChannel =
  | 'positions'
  | 'account'
  | 'trades'
  | 'market'
  | 'system'
  | 'alerts'
  | 'sync_progress'
  | 'job_progress'
  | 'quotes'

/** One price update inside a `quotes` push. */
export interface WSQuoteItem {
  code: string
  price: number
  change_pct: number
  high: number
  low: number
  volume: number
  amount: number
}

/**
 * Payload pushed on the `quotes` channel.
 *
 * Only codes whose price MOVED since the previous tick are included — pushing
 * all 3200 quotes every 3 seconds would be ~400 KB per client per tick.
 */
export interface WSQuotesPayload {
  count: number
  total: number
  items: WSQuoteItem[]
}

export type JobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

/** Progress payload pushed on the `job_progress` channel. */
export interface WSJobProgress {
  job_id: number
  job_type: string
  status: JobStatus
  current: number
  total: number
  pct: number
  message: string | null
}

export interface JobProgress {
  current: number
  total: number
  pct: number
  message: string | null
}

export interface Job {
  id: number
  job_type: string
  status: JobStatus
  progress: JobProgress
  params: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export type WSMessageHandler = (data: unknown) => void
