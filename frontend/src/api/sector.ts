import client from './client'

export function getSectors(strategy?: string) {
  const params: Record<string, unknown> = {}
  if (strategy) params.strategy = strategy
  return client.get('/sectors/', { params })
}

export function getSectorStocks(
  industry: string,
  page: number = 1,
  pageSize: number = 20,
  strategy?: string,
) {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (strategy) params.strategy = strategy
  return client.get(`/sectors/${encodeURIComponent(industry)}`, { params })
}
