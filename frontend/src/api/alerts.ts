import client from './client'

export interface AlertRule {
  id: number
  name: string
  rule_type: 'rank_change' | 'score_threshold' | 'factor_anomaly'
  params: Record<string, unknown>
  enabled: boolean
  notify_wechat: boolean
  created_at: string
  triggered_at: string | null
}

export interface AlertLog {
  id: number
  rule_name: string
  code: string
  name: string
  message: string
  created_at: string
}

export function getAlertRules() {
  return client.get('/alerts/rules')
}

export function createAlertRule(data: {
  name: string
  rule_type: string
  params: string
  enabled?: boolean
  notify_wechat?: boolean
}) {
  return client.post('/alerts/rules', null, { params: data })
}

export function updateAlertRule(id: number, data: Record<string, unknown>) {
  return client.put(`/alerts/rules/${id}`, null, { params: data })
}

export function deleteAlertRule(id: number) {
  return client.delete(`/alerts/rules/${id}`)
}

export function getAlertLogs(page: number = 1, pageSize: number = 20) {
  return client.get('/alerts/logs', { params: { page, page_size: pageSize } })
}

export function manualCheckAlerts() {
  return client.post('/alerts/check')
}
