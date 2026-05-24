// ==================== Stock Types ====================

export interface StockBasic {
  code: string
  name: string
  industry: string | null
}

export interface StockDetail {
  code: string
  name: string
  industry: string | null
}

export interface StockHistory {
  trade_date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount: number
  change_pct: number | null
  ma5?: number
  ma10?: number
  ma20?: number
}

// ==================== Factor Types ====================

export interface FactorItem {
  id: number
  code: string
  factor_name: string
  factor_type: 'technical' | 'fundamental' | 'sentiment'
  value: number
  computed_at: string | null
}

// ==================== Ranking Types ====================

export interface RankingItem {
  id: number
  code: string
  name: string
  industry: string | null
  rank: number
  score: number
  tech_score: number | null
  fund_score: number | null
  sent_score: number | null
}

// ==================== Sector Types ====================

export interface SectorRanking {
  industry: string
  stock_count: number
  avg_score: number
  tech_score: number
  fund_score: number
  sent_score: number
  rank: number
  top_stocks: { code: string; name: string; score: number }[]
}

// ==================== API Response Types ====================

export interface APIResponse<T = unknown> {
  code: number
  message: string
  data: T
}

export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface SyncResult {
  status: string
  message: string
  stock_count: number
}

export interface FactorComputeResult {
  stocks_computed: number
  ranking: {
    status: string
    date: string
    stocks_computed: number
  }
}