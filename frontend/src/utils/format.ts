export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '--'
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  } catch {
    return dateStr
  }
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '--'
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hour = String(d.getHours()).padStart(2, '0')
    const minute = String(d.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hour}:${minute}`
  } catch {
    return dateStr
  }
}

export function formatPrice(price: number | null | undefined): string {
  if (price === null || price === undefined) return '--'
  return `¥${price.toFixed(2)}`
}

export function formatChangePct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return '--'
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

export function formatChangeColor(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return ''
  return pct >= 0 ? 'text-up' : 'text-down'
}

export function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '--'
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿`
  if (num >= 1e4) return `${(num / 1e4).toFixed(2)}万`
  return num.toFixed(0)
}

export function formatVolume(num: number | null | undefined): string {
  if (num === null || num === undefined) return '--'
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿手`
  if (num >= 1e4) return `${(num / 1e4).toFixed(2)}万手`
  return `${num.toFixed(0)}手`
}

export function formatTurnover(num: number | null | undefined): string {
  if (num === null || num === undefined) return '--'
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿`
  if (num >= 1e4) return `${(num / 1e4).toFixed(2)}万`
  return num.toFixed(0)
}

export function formatPercent(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return '--'
  return `${pct.toFixed(2)}%`
}

export function formatMarketCap(num: number | null | undefined): string {
  if (num === null || num === undefined) return '--'
  if (num >= 1e12) return `${(num / 1e12).toFixed(2)}万亿`
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿`
  if (num >= 1e4) return `${(num / 1e4).toFixed(2)}万`
  return num.toFixed(0)
}

export function getRankBadgeClass(rank: number): string {
  if (rank === 1) return 'badge-rank-1'
  if (rank === 2) return 'badge-rank-2'
  if (rank === 3) return 'badge-rank-3'
  return 'badge-rank-normal'
}

export function getScoreColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 65) return '#a78bfa'
  if (score >= 50) return '#60a5fa'
  if (score >= 35) return '#fbbf24'
  return '#f87171'
}