import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import type { RankingItem, StockBasic, StockDetail, StockHistory } from '@/types'

export const useStocksStore = defineStore('stocks', () => {
  const rankings = ref<RankingItem[]>([])
  const stocks = ref<StockBasic[]>([])
  const stockDetail = ref<StockDetail | null>(null)
  const stockHistory = ref<StockHistory[]>([])
  const loading = ref(false)
  const rankingsLoading = ref(false)
  const totalRankings = ref(0)
  const lastUpdate = ref('')

  function setRankings(items: RankingItem[], total: number) {
    rankings.value = items
    totalRankings.value = total
  }

  function setStockList(list: StockBasic[]) {
    stocks.value = list
  }

  function setDetail(detail: StockDetail) {
    stockDetail.value = detail
  }

  function setHistory(history: StockHistory[]) {
    stockHistory.value = history
  }

  function setLoading(state: boolean) {
    loading.value = state
  }

  function setRankingsLoading(state: boolean) {
    rankingsLoading.value = state
  }

  function setLastUpdate(time: string) {
    lastUpdate.value = time
  }

  function clearRankings() {
    rankings.value = []
    totalRankings.value = 0
    lastUpdate.value = ''
  }

  function clearDetail() {
    stockDetail.value = null
    stockHistory.value = []
  }

  return {
    rankings,
    stocks,
    stockDetail,
    stockHistory,
    loading,
    rankingsLoading,
    totalRankings,
    lastUpdate,
    setRankings,
    setStockList,
    setDetail,
    setHistory,
    setLoading,
    setRankingsLoading,
    setLastUpdate,
    clearRankings,
    clearDetail,
  }
})

export const useMonitorStore = defineStore('monitor', () => {
  const wsConnected = ref(false)
  const positions = ref<Record<string, unknown>[]>([])
  const account = reactive({
    initial_capital: 500000,
    cash: 500000,
    total_value: 500000,
    position_value: 0,
    pnl: 0,
    pnl_pct: 0,
    daily_pnl: 0,
    daily_pnl_pct: 0,
    is_active: false,
  })
  const recentTrades = ref<Record<string, unknown>[]>([])

  function setWsConnected(state: boolean) {
    wsConnected.value = state
  }

  function updatePositions(data: Record<string, unknown>[]) {
    positions.value = data
  }

  function updateAccount(data: Record<string, unknown>) {
    Object.assign(account, data)
  }

  function addTrade(data: Record<string, unknown>) {
    recentTrades.value.unshift(data)
    if (recentTrades.value.length > 50) {
      recentTrades.value = recentTrades.value.slice(0, 50)
    }
  }

  return {
    wsConnected, positions, account, recentTrades,
    setWsConnected, updatePositions, updateAccount, addTrade,
  }
})