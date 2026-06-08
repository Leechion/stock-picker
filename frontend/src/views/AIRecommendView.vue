<template>
  <div class="ai-pick-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">AI 明日推荐</h2>
        <span class="page-subtitle">每日 14:30 AI 基于实时行情自主选股</span>
      </div>
      <div class="page-actions">
        <el-tag v-if="stats.today_count > 0" size="small" effect="dark" round class="count-tag">
          今日 {{ stats.today_count }} 只
        </el-tag>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="refreshAll">
          刷新数据
        </el-button>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="card-icon card-icon--scan">
          <el-icon :size="18"><DataLine /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.total_dates }}</div>
          <div class="summary-label">推荐天数</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon card-icon--score">
          <el-icon :size="18"><TrendCharts /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.hit_rate }}%</div>
          <div class="summary-label">命中率</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon" :class="stats.avg_change_pct >= 0 ? 'card-icon--up' : 'card-icon--down'">
          <el-icon :size="18"><CaretTop v-if="stats.avg_change_pct >= 0" /><CaretBottom v-else /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono" :class="stats.avg_change_pct >= 0 ? 'text-up' : 'text-down'">
            {{ stats.avg_change_pct >= 0 ? '+' : '' }}{{ stats.avg_change_pct }}%
          </div>
          <div class="summary-label">平均收益</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="card-icon card-icon--time">
          <el-icon :size="18"><Trophy /></el-icon>
        </div>
        <div class="card-body">
          <div class="summary-value font-mono">{{ stats.total_picks_backtested }}</div>
          <div class="summary-label">已回测</div>
        </div>
      </div>
    </div>

    <!-- Today's Picks -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>今日推荐 ({{ todayPickDate || '暂无' }})</span>
          <el-tag v-if="todayConfidence" size="small" effect="plain" :type="confidenceTagType">
            {{ confidenceLabel }}
          </el-tag>
        </div>
      </template>
      <div v-if="todayPicks.length === 0" class="empty-state">
        <el-empty description="今日暂无推荐数据，请于 14:30 后查看" :image-size="80" />
      </div>
      <div v-else class="pick-list">
        <div v-for="(pick, idx) in todayPicks" :key="pick.id" class="pick-item">
          <div class="pick-rank">#{{ idx + 1 }}</div>
          <div class="pick-info">
            <div class="pick-title">
              <el-link type="primary" :underline="false" @click="goToDetail(pick.code)">
                {{ pick.name }}
              </el-link>
              <span class="pick-code">{{ pick.code }}</span>
              <el-tag
                v-if="pick.next_day_change_pct != null"
                size="small"
                :type="pick.next_day_change_pct > 0 ? 'danger' : 'success'"
                class="pick-result-tag"
              >
                {{ pick.next_day_change_pct > 0 ? '+' : '' }}{{ pick.next_day_change_pct }}%
              </el-tag>
            </div>
            <div class="pick-reason">{{ pick.reason }}</div>
          </div>
          <el-tag
            v-if="pick.confidence"
            size="small"
            effect="plain"
            :type="pickConfidenceTag(pick.confidence)"
            class="pick-confidence"
          >
            {{ pickConfidenceLabel(pick.confidence) }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- History Table -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <span>历史战绩</span>
      </template>
      <el-table
        :data="historyGroups"
        stripe
        size="small"
        v-loading="historyLoading"
        style="cursor: pointer"
      >
        <el-table-column prop="pick_date" label="日期" width="120" />
        <el-table-column prop="count" label="推荐数" width="80" align="center" />
        <el-table-column label="命中" width="100" align="center">
          <template #default="{ row }">
            {{ row.hit_count }}/{{ row.total_backtested }}
          </template>
        </el-table-column>
        <el-table-column label="平均涨幅" width="110" align="center">
          <template #default="{ row }">
            <span
              v-if="row.avg_change_pct != null"
              :class="row.avg_change_pct >= 0 ? 'text-up' : 'text-down'"
            >
              {{ row.avg_change_pct >= 0 ? '+' : '' }}{{ row.avg_change_pct }}%
            </span>
            <span v-else class="text-dim">-</span>
          </template>
        </el-table-column>
        <el-table-column label="推荐标的" min-width="300">
          <template #default="{ row }">
            <div class="history-picks-inline">
              <span v-for="p in row.picks" :key="p.id" class="history-pick-chip">
                {{ p.name }}
                <template v-if="p.next_day_change_pct != null">
                  <span :class="p.next_day_change_pct >= 0 ? 'text-up' : 'text-down'">
                    ({{ p.next_day_change_pct >= 0 ? '+' : '' }}{{ p.next_day_change_pct }}%)
                  </span>
                </template>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap" v-if="historyTotal > 20">
        <el-pagination
          v-model:current-page="historyPage"
          :page-size="20"
          :total="historyTotal"
          layout="prev, pager, next"
          @current-change="loadHistory"
          background
          size="small"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, DataLine, TrendCharts, Trophy, CaretTop, CaretBottom } from '@element-plus/icons-vue'
import { getTodayPicks, getPickHistory, getPickStats } from '@/api/aiPicks'
import type { AIPickItem, HistoryGroup, PickStats } from '@/api/aiPicks'

const router = useRouter()

const loading = ref(false)
const historyLoading = ref(false)
const todayPicks = ref<AIPickItem[]>([])
const todayPickDate = ref('')
const todayConfidence = ref<string | null>(null)
const historyGroups = ref<HistoryGroup[]>([])
const historyPage = ref(1)
const historyTotal = ref(0)
const stats = ref<PickStats>({
  total_dates: 0,
  total_picks_backtested: 0,
  hit_count: 0,
  hit_rate: 0,
  avg_change_pct: 0,
  avg_win_pct: 0,
  avg_loss_pct: 0,
  today_count: 0,
})

const confidenceTagType = computed(() => {
  if (todayConfidence.value === 'high') return 'danger'
  if (todayConfidence.value === 'medium') return 'warning'
  return 'info'
})

const confidenceLabel = computed(() => {
  const map: Record<string, string> = { high: '把握较高', medium: '把握中等', low: '把握较低' }
  return map[todayConfidence.value || ''] || todayConfidence.value || ''
})

function pickConfidenceTag(c: string) {
  if (c === 'high') return 'danger'
  if (c === 'medium') return 'warning'
  return 'info'
}

function pickConfidenceLabel(c: string) {
  const map: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return map[c] || c
}

function goToDetail(code: string) {
  router.push(`/stocks/${code}`)
}

async function loadToday() {
  try {
    const res = await getTodayPicks()
    const data = res.data
    todayPicks.value = data.picks || []
    todayPickDate.value = data.pick_date || ''
    todayConfidence.value = data.confidence
  } catch (e) {
    console.error('Failed to load today picks:', e)
  }
}

async function loadHistory(page: number = 1) {
  historyLoading.value = true
  try {
    const res = await getPickHistory(page)
    const data = res.data
    historyGroups.value = data.items || []
    historyTotal.value = data.total
  } catch (e) {
    console.error('Failed to load history:', e)
  } finally {
    historyLoading.value = false
  }
}

async function loadStats() {
  try {
    const res = await getPickStats()
    stats.value = res.data
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

async function refreshAll() {
  loading.value = true
  await Promise.all([loadToday(), loadStats(), loadHistory(historyPage.value)])
  loading.value = false
}

onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.ai-pick-view {
  max-width: 1000px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title-group .page-title {
  margin: 0 0 4px 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 13px;
  color: var(--text-muted);
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.count-tag {
  font-weight: 600;
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  box-shadow: var(--card-shadow);
  transition: all 0.25s ease;
}

.summary-card:hover {
  box-shadow: var(--card-hover-shadow);
  border-color: rgba(124, 58, 237, 0.15);
}

.card-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(124, 58, 237, 0.08);
  color: #7c3aed;
}

.card-icon--scan { background: rgba(99, 102, 241, 0.08); color: #6366f1; }
.card-icon--score { background: rgba(16, 185, 129, 0.08); color: #10b981; }
.card-icon--up { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.card-icon--down { background: rgba(34, 197, 94, 0.08); color: #22c55e; }
.card-icon--time { background: rgba(245, 158, 11, 0.08); color: #f59e0b; }

.card-body { flex: 1; }

.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.summary-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.section-card {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pick-list {
  display: flex;
  flex-direction: column;
}

.pick-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.pick-item:last-child {
  border-bottom: none;
}

.pick-rank {
  font-size: 18px;
  font-weight: 700;
  color: #7c3aed;
  min-width: 36px;
  line-height: 1.4;
}

.pick-info {
  flex: 1;
  min-width: 0;
}

.pick-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.pick-code {
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'Fira Code', monospace;
}

.pick-result-tag {
  margin-left: 4px;
}

.pick-reason {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.pick-confidence {
  flex-shrink: 0;
  margin-top: 2px;
}

.empty-state {
  padding: 40px 0;
}

.history-picks-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.history-pick-chip {
  font-size: 12px;
  white-space: nowrap;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
