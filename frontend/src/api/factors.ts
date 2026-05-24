import client from './client'

export function getFactors(code: string) {
  return client.get('/factors/', { params: { code } })
}

export function computeFactors() {
  return client.post('/factors/compute')
}