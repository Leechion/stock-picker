<template>
  <div class="trading-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">模拟交易</h2>
        <span class="page-subtitle">虚拟资金实盘模拟 · 策略回测验证</span>
      </div>
      <div class="ws-status">
        <span class="status-dot" :class="monitor.wsConnected ? 'connected' : 'disconnected'" />
        <span class="status-text">{{ monitor.wsConnected ? '实时连接' : '连接中...' }}</span>
      </div>
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
        <el-button type="success" @click="showBuyDialog = true">手动买入</el-button>
      </div>
    </div>

    <!-- Manual Buy Dialog -->
    <el-dialog v-model="showBuyDialog" title="手动买入" width="400px" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="股票代码">
          <el-input v-model="buyForm.code" placeholder="如 600519" />
        </el-form-item>
        <el-form-item label="买入价格（留空自动获取实时价）">
          <el-input-number v-model="buyForm.price" :min="0.01" :precision="2" :step="0.01" style="width: 100%" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBuyDialog = false">取消</el-button>
        <el-button type="primary" :loading="buyLoading" @click="handleManualBuy">确认买入</el-button>
      </template>
    </el-dialog>

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
        <div class="card-label">今日盈亏</div>
        <div class="card-value font-mono" :class="(account.daily_pnl ?? 0) >= 0 ? 'text-up' : 'text-down'">
          {{ (account.daily_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatMoney(account.daily_pnl ?? 0) }}
          <span class="pnl-pct">({{ (account.daily_pnl_pct ?? 0) >= 0 ? '+' : '' }}{{ (account.daily_pnl_pct ?? 0)?.toFixed(2) }}%)</span>
        </div>
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
          <el-button size="small" style="margin-left: auto" @click="exportPositions">导出 CSV</el-button>
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
        <el-table-column prop="change_pct" label="今日涨跌" align="right" width="95">
          <template #default="{ row }">
            <span v-if="row.change_pct != null" class="font-mono" :class="row.change_pct >= 0 ? 'text-up' : 'text-down'">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
            </span>
            <span v-else class="font-mono">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="pnl_pct" label="持仓盈亏" align="right" width="95">
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
      <template #header>
        <div class="section-header">
          <span class="panel-title">交易日志</span>
          <el-button size="small" style="margin-left: auto" @click="exportLogs">导出 CSV</el-button>
        </div>
      </template>
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
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getTradingAccount,
  getTradingPositions,
  getTradingLogs,
  startTradingBot,
  stopTradingBot,
  resetTradingAccount,
  manualBuy,
} from '@/api/trading'
import { useMonitorStore } from '@/store'
import { monitorWs } from '@/utils/websocket'
import { exportToCSV } from '@/utils/export'

const monitor = useMonitorStore()

// Reactive references for template use
const account = computed(() => monitor.account)
const positions = computed(() => monitor.positions)

const actionLoading = ref(false)
const logsLoading = ref(false)
const logsPage = ref(1)
const logsTotal = ref(0)
const tradeLogs = ref<Record<string, unknown>[]>([])

const showBuyDialog = ref(false)
const buyLoading = ref(false)
const buyForm = ref({ code: '', price: undefined as number | undefined })

let _pollTimer: ReturnType<typeof setInterval> | null = null

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

function exportPositions() {
  const data = positions.value
  if (!data.length) return
  exportToCSV(
    ['代码', '名称', '持仓数', '成本价', '现价', '市值', '盈亏', '盈亏率', '止损价', '层数'],
    data.map((p) => [
      String(p.code), String(p.name), Number(p.shares),
      Number(p.avg_cost).toFixed(2),
      Number(p.current_price).toFixed(2),
      Number(p.market_value).toFixed(2),
      Number(p.pnl).toFixed(2),
      Number(p.pnl_pct).toFixed(2) + '%',
      Number(p.stop_loss_price).toFixed(2),
      `${p.tier}/3`,
    ]),
    `持仓_${new Date().toISOString().slice(0, 10)}.csv`,
  )
}

function exportLogs() {
  const data = tradeLogs.value
  if (!data.length) return
  const labelMap: Record<string, string> = { buy: '买入', sell: '卖出', stop_loss: '止损', take_profit: '止盈' }
  exportToCSV(
    ['时间', '操作', '代码', '名称', '价格', '数量', '金额', '盈亏', '原因'],
    data.map((l) => [
      String(l.created_at).replace('T', ' ').substring(0, 19),
      labelMap[String(l.action)] || String(l.action),
      String(l.code), String(l.name),
      Number(l.price).toFixed(2),
      Number(l.shares),
      Number(l.amount).toFixed(2),
      l.pnl != null ? Number(l.pnl).toFixed(2) : '',
      String(l.reason),
    ]),
    `交易日志_${new Date().toISOString().slice(0, 10)}.csv`,
  )
}

function poll() {
  getTradingAccount().then(res => {
    const data = (res as any).data ?? res
    monitor.updateAccount(data)
  }).catch(() => {})
  getTradingPositions().then(res => {
    const data = (res as any).data ?? res
    const arr = Array.isArray(data) ? data : []
    monitor.updatePositions(arr)
  }).catch(() => {})
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
    await loadInitialData()
    loadLogs()
    startPolling()
  } catch { ElMessage.error('启动失败') }
  finally { actionLoading.value = false }
}

async function handleStop() {
  actionLoading.value = true
  try {
    await stopTradingBot()
    ElMessage.success('交易机器人已停止')
    await loadInitialData()
    loadLogs()
    stopPolling()
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
    await loadInitialData()
    loadLogs()
    stopPolling()
  } catch { ElMessage.error('重置失败') }
  finally { actionLoading.value = false }
}

async function handleManualBuy() {
  if (!buyForm.value.code.trim()) {
    ElMessage.warning('请输入股票代码')
    return
  }
  buyLoading.value = true
  try {
    const { data: resp } = await manualBuy(buyForm.value.code.trim(), buyForm.value.price)
    const d = (resp as any).data ?? resp
    ElMessage.success(`买入成功: ${d.name} ${d.shares}股 @ ${d.price?.toFixed(2)}`)
    showBuyDialog.value = false
    buyForm.value = { code: '', price: undefined }
    await loadInitialData()
    loadLogs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '买入失败')
  } finally { buyLoading.value = false }
}

async function loadInitialData() {
  try {
    const [accountRes, positionsRes] = await Promise.all([
      getTradingAccount(),
      getTradingPositions(),
    ])
    const accountData = (accountRes as any).data ?? accountRes
    const positionsData = (positionsRes as any).data ?? positionsRes
    monitor.updateAccount(accountData)
    monitor.updatePositions(Array.isArray(positionsData) ? positionsData : [])
  } catch (e) {
    console.error('[TradingView] loadInitialData failed:', e)
  }
}

function startPolling() {
  if (_pollTimer) return
  poll()
  _pollTimer = setInterval(poll, 3000)
}

function stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer)
    _pollTimer = null
  }
}

onMounted(async () => {
  await loadInitialData()
  loadLogs()

  // Connect WebSocket for real-time updates
  monitorWs.on('open', () => monitor.setWsConnected(true))
  monitorWs.on('close', () => monitor.setWsConnected(false))
  monitorWs.on('positions', (data) => {
    monitor.updatePositions(Array.isArray(data) ? data as Record<string, unknown>[] : [])
  })
  monitorWs.on('account', (data) => {
    if (data && typeof data === 'object') monitor.updateAccount(data as Record<string, unknown>)
  })
  monitorWs.subscribe(['positions', 'account'])
  monitorWs.connect()

  // Only poll when trading is active
  if ((monitor.account as any).is_active) {
    startPolling()
  }
})

onBeforeUnmount(() => {
  monitorWs.disconnect()
  monitor.setWsConnected(false)
  stopPolling()
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

.header-actions {
  display: flex;
  gap: 8px;
}

.font-mono { font-family: 'Fira Code', monospace; }

.account-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
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

.ws-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transition: background-color 0.3s ease;
}

.status-dot.connected {
  background-color: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
}

.status-dot.disconnected {
  background-color: #f59e0b;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
