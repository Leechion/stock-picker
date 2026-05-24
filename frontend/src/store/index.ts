import { defineStore } from 'pinia'
import { ref } from 'vue'
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