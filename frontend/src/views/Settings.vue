<template>
  <div class="settings-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">系统设置</h2>
        <span class="page-subtitle">策略参数配置 · 回测规则管理</span>
</div>
          <el-alert v-if="syncResult" :title="syncResult.message" type="success" show-icon :closable="false" />
        </div>

    <div class="settings-grid">
      <!-- API Config -->
      <el-card shadow="never">
        <template #header><span class="card-title">API 配置</span></template>
        <el-form label-position="top">
          <el-form-item label="API 地址">
            <el-input v-model="apiUrl" placeholder="http://localhost:8000/api" />
            <div class="form-hint">后端服务地址，默认: http://localhost:8000/api</div>
          </el-form-item>
          <el-form-item label="超时时间 (ms)">
            <el-input-number v-model="timeout" :min="5000" :max="60000" :step="1000" />
          </el-form-item>
          <div class="btn-row">
            <el-button type="primary" @click="handleSave" :loading="saving">保存配置</el-button>
            <el-button @click="handleReset">恢复默认</el-button>
          </div>
        </el-form>
      </el-card>

      <!-- Data Sync -->
      <el-card shadow="never">
        <template #header><span class="card-title">数据同步</span></template>
        <div class="sync-section">
          <div class="sync-info">
            <span class="sync-label">股票数量</span>
            <span class="sync-value font-mono">{{ stockCount ?? '--' }} 只</span>
          </div>
          <div class="sync-hint">
            数据源：THS → Sina → 东方财富（自动降级） · 仅沪深主板（00/60） · 增量同步（跳过今日已更新）
          </div>
          <div v-if="syncProgress" class="sync-progress-wrap">
            <el-progress
              :percentage="syncProgress.total > 0 ? Math.round(syncProgress.done / syncProgress.total * 100) : 0"
              :status="syncProgress.status === 'complete' ? 'success' : syncProgress.status === 'cancelled' ? 'exception' : undefined"
              :stroke-width="16"
              :text-inside="true"
            />
            <span class="sync-progress-text">
              {{ syncProgress.status === 'complete' ? '同步完成！' :
                 syncProgress.status === 'cancelled' ? '已取消' :
                 syncProgress.status === 'saving' ? '正在保存...' :
                 `同步中 ${syncProgress.done} / ${syncProgress.total}` }}
            </span>
          </div>
          <div class="sync-buttons">
            <el-button v-if="!syncing" type="primary" :icon="Refresh" @click="handleSync" size="large">
              同步全部股票数据
            </el-button>
            <el-button v-else type="danger" :icon="Close" :loading="cancelling" @click="handleCancelSync" size="large">
              取消同步
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- Factor Compute -->
      <el-card shadow="never">
        <template #header><span class="card-title">因子计算</span></template>
        <p class="card-desc">运行多因子综合打分计算，重新计算所有股票的排名和评分。</p>
        <el-button type="warning" :icon="Cpu" :loading="computing" @click="handleCompute" size="large">
          计算因子排名
        </el-button>
        <el-alert v-if="computeResult" title="计算完成！" type="success" show-icon :closable="false" style="margin-top: 12px" />
      </el-card>

      <!-- Industry Sync -->
      <el-card shadow="never">
        <template #header><span class="card-title">行业数据</span></template>
        <p class="card-desc">从东方财富同步股票的行业板块信息，用于排行榜行业分类和排名。</p>
        <el-button type="primary" :icon="Connection" :loading="syncingIndustry" @click="handleSyncIndustry" size="large">
          同步行业数据
        </el-button>
        <el-alert v-if="industryResult" :title="industryResult" type="success" show-icon :closable="false" style="margin-top: 12px" />
      </el-card>

      <!-- Strategy -->
      <el-card shadow="never">
        <template #header><span class="card-title">策略切换</span></template>
        <p class="card-desc">选择不同的评分策略，切换后排名数据即时更新。</p>
        <div v-loading="strategiesLoading" class="strategy-list">
          <div
            v-for="s in strategies"
            :key="s.slug"
            class="strategy-item"
            :class="{ active: s.active }"
            @click="handleActivate(s.slug)"
          >
            <div class="strategy-head">
              <span v-if="s.active" class="active-dot"></span>
              <span class="strategy-name">{{ s.name }}</span>
            </div>
            <div class="strategy-desc">{{ s.description }}</div>
          </div>
        </div>
        <el-alert v-if="strategyResult" :title="strategyResult" type="success" show-icon :closable="false" style="margin-top: 12px" />
      </el-card>

      <!-- Smart Alerts -->
      <el-card shadow="never" class="alerts-card">
        <template #header><span class="card-title">智能预警</span></template>
        <p class="card-desc">自定义预警规则，每日排名后自动检查并推送通知。</p>
        <el-button type="primary" @click="router.push('/alerts')">管理预警规则</el-button>
      </el-card>

      <!-- System Info -->
      <el-card shadow="never">
        <template #header><span class="card-title">系统信息</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="应用版本">v0.1.0</el-descriptions-item>
          <el-descriptions-item label="前端框架">Vue 3 + TypeScript</el-descriptions-item>
          <el-descriptions-item label="UI 框架">Element Plus</el-descriptions-item>
          <el-descriptions-item label="图表库">ECharts 5</el-descriptions-item>
          <el-descriptions-item label="运行环境">{{ isDev ? '开发' : '生产' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Cpu, Connection, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getStocks, syncAll, syncIndustry } from '@/api/stocks'
import { computeFactors } from '@/api/factors'
import { getStrategies, activateStrategy } from '@/api/strategy'
import { monitorWs } from '@/utils/websocket'
import client from '@/api/client'

const router = useRouter()

const apiUrl = ref('http://localhost:8000/api')
const timeout = ref(30000)
const saving = ref(false)
const syncing = ref(false)
const cancelling = ref(false)
const computing = ref(false)
const syncingIndustry = ref(false)

const stockCount = ref<number | null>(null)
const syncResult = ref<{ message: string } | null>(null)
const computeResult = ref<{ stocks_computed: number; updated_at: string } | null>(null)
const industryResult = ref<string | null>(null)
const syncProgress = ref<{ done: number; total: number; status: string } | null>(null)

const strategies = ref<Array<{ slug: string; name: string; description: string; active: boolean }>>([])
const strategiesLoading = ref(false)
const strategyResult = ref<string | null>(null)

const isDev = import.meta.env.DEV

async function handleSave() {
  saving.value = true
  try {
    localStorage.setItem('apiUrl', apiUrl.value)
    localStorage.setItem('timeout', String(timeout.value))
    ElMessage.success('配置已保存')
  } finally { saving.value = false }
}

function handleReset() {
  apiUrl.value = 'http://localhost:8000/api'
  timeout.value = 30000
  localStorage.removeItem('apiUrl')
  localStorage.removeItem('timeout')
  ElMessage.info('已恢复默认')
}

function handleSyncProgress(data: unknown) {
  const d = data as { done: number; total: number; status: string }
  syncProgress.value = d
  if (d.status === 'complete') {
    syncing.value = false
    syncResult.value = { message: `同步完成，共 ${d.done} 只` }
  } else if (d.status === 'cancelled') {
    syncing.value = false
    ElMessage.warning('同步已取消')
  }
  // 'saving' and 'syncing' — just show progress
}

async function handleSync() {
  syncing.value = true
  syncResult.value = null
  syncProgress.value = null
  // Fire-and-forget: sync takes minutes, rely on WebSocket for progress
  syncAll().catch(() => {
    // Only mark failed if no progress received within 10s
    setTimeout(() => {
      if (syncing.value && !syncProgress.value) {
        syncing.value = false
        ElMessage.error('同步失败')
      }
    }, 10000)
  })
}

async function handleCancelSync() {
  cancelling.value = true
  try {
    await client.post('/stocks/sync-cancel')
    ElMessage.info('已发送取消请求')
  } catch {
    ElMessage.error('取消失败')
  } finally {
    cancelling.value = false
  }
}

async function handleCompute() {
  computing.value = true
  computeResult.value = null
  try {
    const { data } = await computeFactors()
    computeResult.value = { stocks_computed: data.stocks_computed || 0, updated_at: data.updated_at || '' }
    ElMessage.success(`因子计算完成: ${data.stocks_computed || 0} 只`)
  } catch { ElMessage.error('因子计算失败') }
  finally { computing.value = false }
}

async function handleSyncIndustry() {
  syncingIndustry.value = true
  industryResult.value = null
  try {
    const { data } = await syncIndustry()
    industryResult.value = data.message || '行业数据同步完成'
    ElMessage.success('行业数据同步完成')
  } catch { ElMessage.error('行业数据同步失败') }
  finally { syncingIndustry.value = false }
}

async function loadStockCount() {
  try {
    const { data } = await getStocks()
    stockCount.value = (data as unknown[]).length
  } catch { /* ignore */ }
}

async function loadStrategies() {
  strategiesLoading.value = true
  try {
    const { data } = await getStrategies()
    strategies.value = data
  } catch { /* ignore */ }
  finally { strategiesLoading.value = false }
}

async function handleActivate(slug: string) {
  if (strategies.value.find(s => s.slug === slug)?.active) return
  try {
    await activateStrategy(slug)
    strategyResult.value = '策略已切换，排名数据即时生效'
    await loadStrategies()
    ElMessage.success('策略切换成功')
  } catch { ElMessage.error('策略切换失败') }
}

onMounted(() => {
  const savedUrl = localStorage.getItem('apiUrl')
  const savedTimeout = localStorage.getItem('timeout')
  if (savedUrl) apiUrl.value = savedUrl
  if (savedTimeout) timeout.value = Number(savedTimeout)
  loadStockCount()
  loadStrategies()
  monitorWs.on('sync_progress', handleSyncProgress)
  monitorWs.connect()
  monitorWs.subscribe(['sync_progress'])
})

onBeforeUnmount(() => {
  monitorWs.off('sync_progress', handleSyncProgress)
  monitorWs.unsubscribe(['sync_progress'])
})
</script>

<style scoped>
.settings-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header { margin-bottom: 20px; }

.page-title-group {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.page-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 400;
}

.font-mono { font-family: 'Fira Code', monospace; }

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
}

.card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 14px;
  line-height: 1.5;
}

.form-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.btn-row {
  display: flex;
  gap: 8px;
}

.sync-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sync-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: var(--bg-card);
  border-radius: 6px;
}

.sync-days {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sync-hint {
  font-size: 11px;
  color: var(--text-muted);
  padding: 6px 0;
}

.sync-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.sync-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.strategy-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.strategy-item {
  padding: 10px 14px;
  border: 1px solid var(--border-card);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.strategy-item:hover {
  border-color: rgba(124, 58, 237, 0.2);
  background: var(--bg-card-hover);
}

.strategy-item.active {
  border-color: rgba(124, 58, 237, 0.3);
  background: rgba(124, 58, 237, 0.05);
}

.strategy-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}

.active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #a78bfa;
  flex-shrink: 0;
}

.strategy-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.strategy-desc {
  font-size: 12px;
  color: var(--text-muted);
}

/* Alerts */
.alerts-card {
  grid-column: span 2;
}
</style>
