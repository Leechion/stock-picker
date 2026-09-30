import client from './client'

/**
 * GET /rankings/ — 服务端分页的排名列表。
 *
 * 后端当前契约（本轮）:
 *   - page       : 页码，>= 1
 *   - page_size  : 每页条数，1..200
 *   - strategy   : 策略 slug，可选
 *   - search     : 按股票代码/名称匹配，可选；**服务端过滤，跨页生效**
 *
 * 后端【尚未支持】industry 查询参数（FastAPI 会静默忽略未知 query 参数）。
 * 因此调用方不得把 industry 当成"完整筛选"呈现——见
 * `views/StockRanking.vue` 中的降级方案说明。待后端新增该参数后，再在此处
 * 追加 `if (industry) params.industry = industry` 并把 UI 提示改回完整筛选。
 */
export function getRankings(
  page: number = 1,
  pageSize: number = 20,
  strategy?: string,
  search?: string
) {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (strategy) params.strategy = strategy
  if (search) params.search = search
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