import client from './client'

export interface AIPickItem {
  id: number
  code: string
  name: string
  reason: string
  confidence: string | null
  price_at_pick: number | null
  next_day_open: number | null
  next_day_close: number | null
  next_day_change_pct: number | null
  pick_date: string
}

export interface TodayPicksResponse {
  picks: AIPickItem[]
  pick_date: string
  confidence: string | null
}

export interface HistoryGroup {
  pick_date: string
  picks: AIPickItem[]
  count: number
  hit_count: number
  total_backtested: number
  avg_change_pct: number | null
}

export interface PickStats {
  total_dates: number
  total_picks_backtested: number
  hit_count: number
  hit_rate: number
  avg_change_pct: number
  avg_win_pct: number
  avg_loss_pct: number
  today_count: number
}

export function getTodayPicks() {
  return client.get<any, { code: number; message: string; data: TodayPicksResponse }>('/ai-picks/today')
}

export function getPickHistory(page: number = 1, pageSize: number = 20) {
  return client.get<any, { code: number; message: string; data: { items: HistoryGroup[]; total: number; page: number; page_size: number } }>(
    '/ai-picks/history',
    { params: { page, page_size: pageSize } }
  )
}

export function getPickStats() {
  return client.get<any, { code: number; message: string; data: PickStats }>('/ai-picks/stats')
}
