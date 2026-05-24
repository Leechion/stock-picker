import client from './client'

export function getStrategies() {
  return client.get('/strategies/')
}

export function getActiveStrategy() {
  return client.get('/strategies/active')
}

export function activateStrategy(slug: string) {
  return client.post(`/strategies/${slug}/activate`)
}
