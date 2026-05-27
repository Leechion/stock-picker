import client from './client'

export interface BacktestResult {
  status: string
  period: { start: string; end: string }
  config: { top_n: number; hold_days: number }
  metrics: {
    total_return_pct: number
    avg_period_return_pct: number
    win_rate: number
    sharpe_ratio: number
    max_drawdown_pct: number
    num_periods: number
  }
  periods: {
    date: string
    top_codes: string[]
    avg_return: number
    n_with_data: number
    cumulative_return: number
    drawdown: number
  }[]
}

export function runBacktest(days: number = 180, topN: number = 10, holdDays: number = 5) {
  return client.post('/backtest/run', null, {
    params: { days, top_n: topN, hold_days: holdDays },
  })
}
