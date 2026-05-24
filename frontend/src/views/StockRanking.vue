<template>
  <div class="ranking-view">
    <div class="page-header">
      <h2 class="page-title">股票排行榜</h2>
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="refreshData">
        刷新排名
      </el-button>
    </div>

    <!-- Summary Cards -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="summary-value">{{ totalRankings }}</div>
        <div class="summary-label">参与排名</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ lastUpdate || '--' }}</div>
        <div class="summary-label">最后更新</div>
      </div>
      <div class="summary-card">
        <div class="summary-value top3-row">
          <template v-if="top3.length > 0">
            <span v-for="(item, idx) in top3" :key="item.code" class="top3-chip">
              <span class="rank-num" :class="`rank-${idx + 1}`">{{ idx + 1 }}</span>
              <el-link type="primary" :underline="false" @click="goToDetail(item.code)">
                {{ item.name }}
              </el-link>
            </span>
          </template>
          <span v-else class="text-dim">--</span>
        </div>
        <div class="summary-label">TOP 3</div>
      </div>
      <div class="summary-card">
        <div class="summary-value font-mono">{{ avgScore }}</div>
        <div class="summary-label">平均评分</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <el-select v-model="industryFilter" placeholder="全部行业" clearable size="default" style="width: 160px">
        <el-option v-for="ind in industryList" :key="ind" :label="ind" :value="ind" />
      </el-select>
      <el-input v-model="searchQuery" placeholder="搜索代码或名称" :prefix-icon="Search" clearable style="width: 200px" />
    </div>

    <!-- Table -->
    <el-card shadow="never" class="table-card">
      <StockTable
        :data="filteredRankings"
        :total="totalRankings"
        :loading="rankingsLoading"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        @row-click="handleRowClick"
      />
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, onBeforeRouteUpdate } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { useStocksStore } from '@/store'
import { getRankings } from '@/api/ranking'
import { getActiveStrategy } from '@/api/strategy'
import StockTable from '@/components/StockTable.vue'
import type { PaginatedData, RankingItem } from '@/types'

const store = useStocksStore()
const router = useRouter()

const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const industryFilter = ref('')
const searchQuery = ref('')
const activeStrategy = ref('')

const rankings = computed(() => store.rankings)
const totalRankings = computed(() => store.totalRankings)
const rankingsLoading = computed(() => store.rankingsLoading)
const lastUpdate = computed(() => store.lastUpdate)

const top3 = computed(() => rankings.value.slice(0, 3))

const avgScore = computed(() => {
  if (rankings.value.length === 0) return '--'
  const avg = rankings.value.reduce((s, r) => s + (r.score ?? 0), 0) / rankings.value.length
  return avg.toFixed(1)
})

const industryList = computed(() => {
  const set = new Set<string>()
  rankings.value.forEach((r) => { if (r.industry) set.add(r.industry) })
  return Array.from(set).sort()
})

const filteredRankings = computed(() => {
  let list = rankings.value
  if (industryFilter.value) {
    list = list.filter((r) => r.industry === industryFilter.value)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter(
      (r) => r.code.toLowerCase().includes(q) || (r.name || '').includes(q)
    )
  }
  return list
})

async function loadActiveStrategy() {
  try {
    const { data } = await getActiveStrategy()
    activeStrategy.value = data.slug || ''
  } catch { /* ignore */ }
}

async function loadRankings() {
  store.setRankingsLoading(true)
  try {
    const { data } = await getRankings(currentPage.value, pageSize.value, activeStrategy.value)
    const pageData = data as PaginatedData<RankingItem>
    const items = pageData.items || []
    store.setRankings(items, pageData.total || items.length)
    store.setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
  } catch { /* handled */ }
  finally { store.setRankingsLoading(false) }
}

async function refreshData() {
  loading.value = true
  try { await loadRankings() }
  finally { loading.value = false }
}

function goToDetail(code: string) { router.push(`/stocks/${code}`) }
function handleRowClick(row: RankingItem) { router.push(`/stocks/${row.code}`) }

// Reload when navigating back to this page (e.g. after strategy switch in Settings)
onBeforeRouteUpdate((to) => {
  if (to.path === '/') {
    loadActiveStrategy().then(() => loadRankings())
  }
})

onMounted(async () => {
  await loadActiveStrategy()
  loadRankings()
})
watch([currentPage, pageSize], () => { loadRankings() })
</script>

<style scoped>
.ranking-view {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

.summary-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 14px 16px;
  transition: all 0.2s ease;
}

.summary-card:hover {
  border-color: rgba(124, 58, 237, 0.15);
}

.summary-value {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
  margin-bottom: 4px;
}

.summary-label {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  letter-spacing: 0.02em;
}

.top3-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.top3-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

.rank-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 10px;
  color: #fff;
}

.rank-1 { background: linear-gradient(135deg, #ffd700, #f59e0b); }
.rank-2 { background: rgba(248, 250, 252, 0.15); color: rgba(248, 250, 252, 0.7); }
.rank-3 { background: rgba(248, 250, 252, 0.08); color: rgba(248, 250, 252, 0.5); }

.text-dim { color: var(--text-muted); font-size: 14px; }

.font-mono { font-family: 'Fira Code', monospace; }

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  align-items: center;
}

.table-card {
  border-radius: 10px;
}
</style>
