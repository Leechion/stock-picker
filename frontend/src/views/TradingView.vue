<template>
  <div class="trading-view">
    <div class="page-header">
      <h2 class="page-title">模拟交易</h2>
      <div class="header-actions">
        <el-button
          v-if="!account.is_active"
          type="primary"
          :loading="actionLoading"
          @click="handleStart"
        >
          启动交易
        </el-button>
        <el-button
          v-else
          type="danger"
          :loading="actionLoading"
          @click="handleStop"
        >
          停止交易
        </el-button>
        <el-button :loading="actionLoading" @click="handleReset">重置账户</el-button>
      </div>
    </div>

    <!-- Account Overview -->
    <div class="account-cards">
      <div class="account-card">
        <div class="card-label">总资产</div>
        <div class="card-value font-mono">{{ formatMoney(account.total_value) }}</div>
      </div>
      <div class="account-card">
        <div class="card-label">可用资金</div>
        <div class="card-value font-mono">{{ formatMoney(account.cash) }}</div>
      </div>
      <div class="account-card">
        <div class="card-label">持仓市值</div>
        <div class="card-value font-mono">{{ formatMoney(account.position_value) }}</div>
      </div>
      <div class="account-card">
        <div class="card-label">总盈亏</div>
        <div class="card-value font-mono" :class="account.pnl >= 0 ? 'text-up' : 'text-down'">
          {{ account.pnl >= 0 ? '+' : '' }}{{ formatMoney(account.pnl) }}
          <span class="pnl-pct">({{ account.pnl_pct >= 0 ? '+' : '' }}{{ account.pnl_pct?.toFixed(2) }}%)</span>
        </div>
      </div>
    </div>

    <!-- Positions Table -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span class="panel-title">当前持仓</span>
          <span class="font-mono position-count">{{ positions.length }} / 10</span>
        </div>
      </template>
      <el-table :data="positions" border stripe style="width: 100%">
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="shares" label="持仓数" align="right" width="90">
          <template #default="{ row }">
            <span class="font-mono">{{ row.shares }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_cost" label="成本价" align="right" width="100">
          <template #default="{ row }">
            <span class="font-mono">{{ row.avg_cost?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="current_price" label="现价" align="right" width="100">
          <template #default="{ row }">
            <span class="font-mono">{{ row.current_price?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="market_value" label="市值" align="right" width="110">
          <template #default="{ row }">
            <span class="font-mono">{{ formatMoney(row.market_value) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="pnl" label="盈亏" align="right" width="110">
          <template #default="{ row }">
            <span class="font-mono" :class="row.pnl >= 0 ? 'text-up' : 'text-down'">
              {{ row.pnl >= 0 ? '+' : '' }}{{ formatMoney(row.pnl) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="pnl_pct" label="盈亏%" align="right" width="90">
          <template #default="{ row }">
            <span class="font-mono" :class="row.pnl_pct >= 0 ? 'text-up' : 'text-down'">
              {{ row.pnl_pct >= 0 ? '+' : '' }}{{ row.pnl_pct?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="stop_loss_price" label="止损价" align="right" width="100">
          <template #default="{ row }">
            <span class="font-mono">{{ row.stop_loss_price?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="tier" label="层数" align="center" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="row.tier === 1 ? 'info' : row.tier === 2 ? 'warning' : 'danger'">
              {{ row.tier }}/3
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="positions.length === 0" description="暂无持仓" :image-size="80" />
    </el-card>

    <!-- Trade Logs Table -->
    <el-card shadow="never" class="section-card">
      <template #header><span class="panel-title">交易日志</span></template>
      <el-table :data="tradeLogs" border stripe style="width: 100%" v-loading="logsLoading">
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="action" label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="actionTagType(row.action)" effect="plain">
              {{ actionLabel(row.action) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="股票" width="150">
          <template #default="{ row }">
            {{ row.code }} {{ row.name }}
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价格" align="right" width="90">
          <template #default="{ row }">
            <span class="font-mono">{{ row.price?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="shares" label="数量" align="right" width="80">
          <template #default="{ row }">
            <span class="font-mono">{{ row.shares }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="amount" label="金额" align="right" width="120">
          <template #default="{ row }">
            <span class="font-mono">{{ formatMoney(row.amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="pnl" label="盈亏" align="right" width="110">
          <template #default="{ row }">
            <span v-if="row.pnl != null" class="font-mono" :class="row.pnl >= 0 ? 'text-up' : 'text-down'">
              {{ row.pnl >= 0 ? '+' : '' }}{{ formatMoney(row.pnl) }}
            </span>
            <span v-else class="font-mono">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="200" />
      </el-table>
      <div class="pagination-wrap" v-if="logsTotal > 0">
        <el-pagination
          v-model:current-page="logsPage"
          :page-size="20"
          :total="logsTotal"
          layout="prev, pager, next"
          small
          background
          @current-change="loadLogs"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getTradingAccount,
  getTradingPositions,
  getTradingLogs,
  startTradingBot,
  stopTradingBot,
  resetTradingAccount,
} from '@/api/trading'

const actionLoading = ref(false)
const logsLoading = ref(false)
const logsPage = ref(1)
const logsTotal = ref(0)

const account = reactive({
  initial_capital: 500000,
  cash: 500000,
  total_value: 500000,
  position_value: 0,
  pnl: 0,
  pnl_pct: 0,
  is_active: false,
})

const positions = ref<Record<string, unknown>[]>([])
const tradeLogs = ref<Record<string, unknown>[]>([])

let refreshTimer: ReturnType<typeof setInterval> | null = null

function formatMoney(val: number): string {
  if (val == null) return '--'
  return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(str: string): string {
  if (!str) return '--'
  return str.replace('T', ' ').substring(0, 19)
}

function actionLabel(action: string): string {
  const map: Record<string, string> = { buy: '买入', sell: '卖出', stop_loss: '止损', take_profit: '止盈' }
  return map[action] || action
}

function actionTagType(action: string): string {
  const map: Record<string, string> = { buy: 'danger', sell: 'success', stop_loss: 'warning', take_profit: 'primary' }
  return map[action] || ''
}

async function loadAccount() {
  try {
    const { data } = await getTradingAccount()
    Object.assign(account, data)
  } catch { /* silent */ }
}

async function loadPositions() {
  try {
    const { data } = await getTradingPositions()
    positions.value = data || []
  } catch { positions.value = [] }
}

async function loadLogs() {
  logsLoading.value = true
  try {
    const { data } = await getTradingLogs(logsPage.value, 20)
    tradeLogs.value = data?.items || []
    logsTotal.value = data?.total || 0
  } catch { tradeLogs.value = [] }
  finally { logsLoading.value = false }
}

async function handleStart() {
  actionLoading.value = true
  try {
    await startTradingBot()
    ElMessage.success('交易机器人已启动')
    account.is_active = true
  } catch { ElMessage.error('启动失败') }
  finally { actionLoading.value = false }
}

async function handleStop() {
  actionLoading.value = true
  try {
    await stopTradingBot()
    ElMessage.success('交易机器人已停止')
    account.is_active = false
  } catch { ElMessage.error('停止失败') }
  finally { actionLoading.value = false }
}

async function handleReset() {
  try {
    await ElMessageBox.confirm('确定要重置模拟账户吗？所有持仓和交易记录将被清除。', '确认重置', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  actionLoading.value = true
  try {
    await resetTradingAccount()
    ElMessage.success('账户已重置')
    await loadAll()
  } catch { ElMessage.error('重置失败') }
  finally { actionLoading.value = false }
}

async function loadAll() {
  await Promise.all([loadAccount(), loadPositions(), loadLogs()])
}

function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    if (account.is_active) {
      loadAccount()
      loadPositions()
    }
  }, 30000) // Refresh every 30s when active
}

onMounted(() => {
  loadAll()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.trading-view {
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

.header-actions {
  display: flex;
  gap: 8px;
}

.font-mono { font-family: 'Fira Code', monospace; }

.account-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.account-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 16px;
  transition: all 0.2s ease;
}

.account-card:hover {
  background: var(--bg-card-hover);
}

.card-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.card-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.pnl-pct {
  font-size: 13px;
  font-weight: 400;
  opacity: 0.7;
}

.section-card {
  margin-bottom: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.position-count {
  font-size: 12px;
  color: var(--text-muted);
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
