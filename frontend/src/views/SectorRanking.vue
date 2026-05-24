<template>
  <div class="sector-view">
    <div class="page-header">
      <h2 class="page-title">板块排行</h2>
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadSectors">
        刷新
      </el-button>
    </div>

    <!-- Summary Cards -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="summary-value">{{ sectors.length }}</div>
        <div class="summary-label">板块数量</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ topSector?.industry || '--' }}</div>
        <div class="summary-label">最强板块</div>
      </div>
      <div class="summary-card">
        <div class="summary-value font-mono">{{ topSector?.avg_score?.toFixed(1) || '--' }}</div>
        <div class="summary-label">最高均分</div>
      </div>
      <div class="summary-card">
        <div class="summary-value font-mono">{{ totalStocks }}</div>
        <div class="summary-label">覆盖股票</div>
      </div>
    </div>

    <!-- Sector Table -->
    <el-card shadow="never" class="table-card">
      <el-table
        :data="sectors"
        :loading="loading"
        stripe
        style="width: 100%"
        @row-click="handleRowClick"
        row-class-name="sector-row"
      >
        <el-table-column type="index" label="排名" width="68" align="center" fixed>
          <template #default="{ $index }">
            <span :class="getRankBadgeClass($index + 1)">{{ $index + 1 }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="industry" label="板块" min-width="130" fixed>
          <template #default="{ row }">
            <span class="sector-name">{{ row.industry }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="stock_count" label="股票数" width="85" align="center" sortable>
          <template #default="{ row }">
            <span class="font-mono">{{ row.stock_count }}</span>
          </template>
        </el-table-column>

        <el-table-column label="综合均分" width="110" align="center" sortable
          :sort-method="(a: SectorRanking, b: SectorRanking) => a.avg_score - b.avg_score">
          <template #default="{ row }">
            <span class="score-value font-mono" :style="{ color: getScoreColor(row.avg_score) }">
              {{ row.avg_score.toFixed(1) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="技术面" width="90" align="center" sortable
          :sort-method="(a: SectorRanking, b: SectorRanking) => a.tech_score - b.tech_score">
          <template #default="{ row }">
            <span class="mini-score font-mono" :style="{ color: getScoreColor(row.tech_score + 50) }">
              {{ row.tech_score.toFixed(1) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="基本面" width="90" align="center" sortable
          :sort-method="(a: SectorRanking, b: SectorRanking) => a.fund_score - b.fund_score">
          <template #default="{ row }">
            <span class="mini-score font-mono" :style="{ color: getScoreColor(row.fund_score + 50) }">
              {{ row.fund_score.toFixed(1) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="情绪面" width="90" align="center" sortable
          :sort-method="(a: SectorRanking, b: SectorRanking) => a.sent_score - b.sent_score">
          <template #default="{ row }">
            <span class="mini-score font-mono" :style="{ color: getScoreColor(row.sent_score + 50) }">
              {{ row.sent_score.toFixed(1) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="TOP 3" min-width="200">
          <template #default="{ row }">
            <div class="top3-list">
              <span v-for="(s, i) in row.top_stocks" :key="s.code" class="top3-item">
                <span class="top3-rank">{{ i + 1 }}</span>
                <el-link type="primary" :underline="false" @click.stop="goToStock(s.code)">
                  {{ s.name }}
                </el-link>
                <span class="top3-score font-mono">{{ s.score }}</span>
                <span v-if="i < row.top_stocks.length - 1" class="top3-sep">|</span>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Sector Detail Drawer -->
    <el-drawer
      v-model="drawerVisible"
      :title="selectedSector?.industry + ' - 个股排行'"
      size="680px"
      :destroy-on-close="true"
    >
      <div v-if="selectedSector" class="drawer-content">
        <div class="drawer-stats">
          <div class="drawer-stat">
            <span class="drawer-stat-label">板块均分</span>
            <span class="drawer-stat-value font-mono" :style="{ color: getScoreColor(selectedSector.avg_score) }">
              {{ selectedSector.avg_score.toFixed(1) }}
            </span>
          </div>
          <div class="drawer-stat">
            <span class="drawer-stat-label">股票数量</span>
            <span class="drawer-stat-value font-mono">{{ selectedSector.stock_count }}</span>
          </div>
          <div class="drawer-stat">
            <span class="drawer-stat-label">技术面</span>
            <span class="drawer-stat-value font-mono">{{ selectedSector.tech_score.toFixed(1) }}</span>
          </div>
          <div class="drawer-stat">
            <span class="drawer-stat-label">基本面</span>
            <span class="drawer-stat-value font-mono">{{ selectedSector.fund_score.toFixed(1) }}</span>
          </div>
          <div class="drawer-stat">
            <span class="drawer-stat-label">情绪面</span>
            <span class="drawer-stat-value font-mono">{{ selectedSector.sent_score.toFixed(1) }}</span>
          </div>
        </div>

        <el-table :data="sectorStocks" :loading="stocksLoading" stripe>
          <el-table-column label="板块排名" width="90" align="center">
            <template #default="{ $index }">
              <span :class="getRankBadgeClass((stocksPage - 1) * stocksPageSize + $index + 1)">
                {{ (stocksPage - 1) * stocksPageSize + $index + 1 }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="代码" width="100" align="center">
            <template #default="{ row }">
              <span class="font-mono">{{ row.code }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="100" />
          <el-table-column label="综合评分" width="110" align="center" sortable
            :sort-method="(a: any, b: any) => a.score - b.score">
            <template #default="{ row }">
              <span class="font-mono" :style="{ color: getScoreColor(row.score) }">{{ row.score.toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="技术" width="80" align="center">
            <template #default="{ row }">
              <span class="mini-score font-mono">{{ row.tech_score.toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="基本" width="80" align="center">
            <template #default="{ row }">
              <span class="mini-score font-mono">{{ row.fund_score.toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="情绪" width="80" align="center">
            <template #default="{ row }">
              <span class="mini-score font-mono">{{ row.sent_score.toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ row }">
              <el-link type="primary" :underline="false" @click="goToStock(row.code)">详情</el-link>
            </template>
          </el-table-column>
        </el-table>

        <div class="drawer-pagination">
          <el-pagination
            v-model:current-page="stocksPage"
            :page-size="stocksPageSize"
            :total="stocksTotal"
            layout="prev, pager, next"
            background
            small
            @current-change="loadSectorStocks"
          />
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { getSectors, getSectorStocks } from '@/api/sector'
import { getActiveStrategy } from '@/api/strategy'
import { getScoreColor, getRankBadgeClass } from '@/utils/format'
import type { SectorRanking } from '@/types'

const router = useRouter()

const loading = ref(false)
const sectors = ref<SectorRanking[]>([])
const activeStrategy = ref('')

const drawerVisible = ref(false)
const selectedSector = ref<SectorRanking | null>(null)
const sectorStocks = ref<any[]>([])
const stocksLoading = ref(false)
const stocksPage = ref(1)
const stocksPageSize = ref(20)
const stocksTotal = ref(0)

const topSector = computed(() => sectors.value[0] || null)
const totalStocks = computed(() => sectors.value.reduce((s, r) => s + r.stock_count, 0))

async function loadSectors() {
  loading.value = true
  try {
    const { data } = await getSectors(activeStrategy.value)
    sectors.value = Array.isArray(data) ? data : []
  } catch { /* ignore */ }
  finally { loading.value = false }
}

async function handleRowClick(row: SectorRanking) {
  selectedSector.value = row
  stocksPage.value = 1
  drawerVisible.value = true
  await loadSectorStocks()
}

async function loadSectorStocks() {
  if (!selectedSector.value) return
  stocksLoading.value = true
  try {
    const { data } = await getSectorStocks(
      selectedSector.value.industry,
      stocksPage.value,
      stocksPageSize.value,
      activeStrategy.value,
    )
    sectorStocks.value = data.items || []
    stocksTotal.value = data.total || 0
  } catch { /* ignore */ }
  finally { stocksLoading.value = false }
}

function goToStock(code: string) {
  router.push(`/stocks/${code}`)
}

onMounted(async () => {
  try {
    const { data } = await getActiveStrategy()
    activeStrategy.value = data.slug || ''
  } catch { /* ignore */ }
  await loadSectors()
})
</script>

<style scoped>
.sector-view {
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
  color: var(--text-muted);
}

.font-mono { font-family: 'Fira Code', monospace; }

.table-card { border-radius: 10px; }

.sector-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.score-value {
  font-size: 14px;
  font-weight: 600;
}

.mini-score {
  font-size: 13px;
  font-weight: 600;
}

.top3-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
}

.top3-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
}

.top3-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 3px;
  background: var(--bg-card);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary);
}

.top3-score {
  font-size: 11px;
  color: var(--text-muted);
}

.top3-sep {
  color: var(--text-muted);
  margin: 0 2px;
}

/* Drawer */
.drawer-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.drawer-stat {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 8px;
  padding: 10px 14px;
  text-align: center;
  min-width: 80px;
}

.drawer-stat-label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.drawer-stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.drawer-pagination {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}

/* Rank badges */
.badge-rank-1 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: linear-gradient(135deg, #ffd700, #f59e0b);
  color: #fff;
  font-weight: 600;
  font-size: 11px;
}

.badge-rank-2 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.12);
  color: rgba(248, 250, 252, 0.7);
  font-weight: 600;
  font-size: 11px;
}

.badge-rank-3 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.06);
  color: rgba(248, 250, 252, 0.5);
  font-weight: 600;
  font-size: 11px;
}

.badge-rank-normal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.04);
  color: rgba(248, 250, 252, 0.5);
  font-weight: 500;
  font-size: 11px;
}
</style>
