import client from './client'

export function getStocks(params?: { code?: string; name?: string }) {
  return client.get('/stocks/', { params })
}

export function getStockHistory(
  code: string,
  days: number = 120
) {
  return client.get('/stocks/history', {
    params: { code, days },
  })
}

export function getStockInfo(code: string) {
  return client.get('/stocks/info', { params: { code } })
}

export function getStockFundamentals(code: string) {
  return client.get('/stocks/fundamentals', { params: { code } })
}

export function syncAll(days_back?: number) {
  return client.post('/stocks/sync', null, { params: { days_back } })
}

export function syncIndustry() {
  return client.post('/stocks/sync-industry')
}

export function getRealtimeQuote(code: string) {
  return client.get('/stocks/quote', { params: { code } })
}

export function getIntradayData(code: string, period: number = 5) {
  return client.get('/stocks/intraday', { params: { code, period } })
}