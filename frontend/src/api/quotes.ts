import client from './client'

export interface Quote {
  code: string
  name: string
  price: number
  prev_close: number
  open: number
  high: number
  low: number
  volume: number
  amount: number
  change_pct: number
  turnover_rate: number | null
  pe: number | null
  pb: number | null
  ts: string
}

export interface MarketOverview {
  session: string
  is_trading: boolean
  time: string
  breadth: { total: number; rising: number; falling: number; flat: number }
  poller: {
    ticks: number
    errors: number
    last_at: string | null
    last_count: number
    running: boolean
  }
  snapshot: { count: number; at: string } | null
}

/**
 * Fetch quotes for specific codes. Served from the server's in-memory
 * snapshot, so this never blocks on the upstream data provider.
 */
export function getQuotes(codes: string[]) {
  return client.get('/quotes/', { params: { codes: codes.join(',') } })
}

/** Market breadth + poller health, for a header or status indicator. */
export function getMarketOverview() {
  return client.get('/quotes/market')
}
