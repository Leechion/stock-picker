import client from './client'

export function getRankings(
  page: number = 1,
  pageSize: number = 20,
  strategy?: string
) {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (strategy) params.strategy = strategy
  return client.get('/rankings/', { params })
}

export function getStockRank(code: string, strategy?: string) {
  const params: Record<string, unknown> = {}
  if (strategy) params.strategy = strategy
  return client.get(`/rankings/${code}`, { params })
}

export function getRankingHistory(code: string, days: number = 30, strategy?: string) {
  const params: Record<string, unknown> = { days }
  if (strategy) params.strategy = strategy
  return client.get(`/rankings/history/${code}`, { params })
}

export function getPeerStocks(code: string, strategy?: string) {
  const params: Record<string, unknown> = {}
  if (strategy) params.strategy = strategy
  return client.get(`/rankings/peers/${code}`, { params })
}