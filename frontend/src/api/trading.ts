import client from './client'

export function getTradingAccount() {
  return client.get('/trading/account')
}

export function getTradingPositions() {
  return client.get('/trading/positions')
}

export function getTradingLogs(page = 1, page_size = 20) {
  return client.get('/trading/logs', { params: { page, page_size } })
}

export function startTradingBot() {
  return client.post('/trading/start')
}

export function stopTradingBot() {
  return client.post('/trading/stop')
}

export function resetTradingAccount() {
  return client.post('/trading/reset')
}

export function manualBuy(code: string, price?: number) {
  const params: Record<string, string | number> = { code }
  if (price != null) params.price = price
  return client.post('/trading/manual-buy', null, { params })
}
