<template>
  <div class="backtest-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">策略回测</h2>
        <span class="page-subtitle">历史排名模拟 · 净值曲线分析</span>
      </div>
    </div>

    <!-- Config -->
    <el-card shadow="never" class="config-card">
      <div class="config-row">
        <div class="config-item">
          <span class="config-label">回测天数</span>
          <el-input-number v-model="form.days" :min="30" :max="720" :step="30" size="small" />
        </div>
        <div class="config-item">
          <span class="config-label">选股数量 (Top N)</span>
          <el-input-number v-model="form.topN" :min="1" :max="50" size="small" />
        </div>
        <div class="config-item">
          <span class="config-label">持有天数</span>
          <el-input-number v-model="form.holdDays" :min="1" :max="20" size="small" />
        </div>
        <el-button type="primary" :loading="running" @click="runTest">运行回测</el-button>
      </div>
    </el-card>

    <!-- Results -->
    <template v-if="result">
      <!-- Metrics Cards -->
      <div class="metrics-cards">
        <div class="metric-card">
          <div class="metric-label">总收益率</div>
          <div class="metric-value font-mono" :class="result.metrics.total_return_pct >= 0 ? 'text-up' : 'text-down'">
            {{ result.metrics.total_return_pct >= 0 ? '+' : '' }}{{ result.metrics.total_return_pct.toFixed(2) }}%
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">胜率</div>
          <div class="metric-value font-mono">{{ (result.metrics.win_rate * 100).toFixed(1) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">夏普比率</div>
          <div class="metric-value font-mono">{{ result.metrics.sharpe_ratio.toFixed(2) }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">最大回撤</div>
          <div class="metric-value font-mono text-down">{{ result.metrics.max_drawdown_pct.toFixed(2) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">回测期数</div>
          <div class="metric-value font-mono">{{ result.metrics.num_periods }}</div>
        </div>
      </div>

      <!-- Equity Curve Chart -->
      <el-card shadow="never" class="chart-card">
        <template #header><span class="panel-title">净值曲线</span></template>
        <div ref="chartRef" class="equity-chart"></div>
      </el-card>

      <!-- Period Details Table -->
      <el-card shadow="never" class="table-card">
        <template #header><span class="panel-title">每期明细</span></template>
        <el-table :data="result.periods" border stripe size="small" style="width: 100%"
          :default-sort="{ prop: 'date', order: 'descending' }">
          <el-table-column prop="date" label="日期" width="120" align="center" sortable />
          <el-table-column prop="top_codes" label="Top 选股" min-width="160">
            <template #default="{ row }">
              <span class="font-mono" style="font-size: 11px">{{ (row.top_codes || []).join(', ') }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="avg_return" label="期间收益" width="110" align="right" sortable>
            <template #default="{ row }">
              <span class="font-mono" :class="row.avg_return >= 0 ? 'text-up' : 'text-down'">
                {{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="cumulative_return" label="累计收益" width="110" align="right" sortable>
            <template #default="{ row }">
              <span class="font-mono" :class="(row.cumulative_return ?? 0) >= 0 ? 'text-up' : 'text-down'">
                {{ (row.cumulative_return ?? 0) >= 0 ? '+' : '' }}{{ (row.cumulative_return ?? 0).toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="drawdown" label="回撤" width="100" align="right" sortable>
            <template #default="{ row }">
              <span class="font-mono text-down">{{ (row.drawdown ?? 0).toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="n_with_data" label="有效数据" width="90" align="center" />
        </el-table>
      </el-card>
    </template>

    <el-empty v-else-if="!running" description="配置参数后点击「运行回测」开始分析" :image-size="120" />
  </div>
</template>

<script lang="ts" setup>
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { runBacktest } from '@/api/backtest'
import type { BacktestResult } from '@/api/backtest'

const form = ref({ days: 180, topN: 10, holdDays: 5 })
const running = ref(false)
const result = ref<BacktestResult | null>(null)
const chartRef = ref<HTMLDivElement>()
const chartInstance = ref<echarts.ECharts>()

function isDark() {
  return document.documentElement.classList.contains('dark')
}

async function runTest() {
  running.value = true
  result.value = null
  try {
    const { data } = await runBacktest(form.value.days, form.value.topN, form.value.holdDays)
    if (data.status !== 'success') {
      ElMessage.warning(data.message || '回测未产生结果')
      return
    }
    result.value = data
    await nextTick()
    renderChart()
  } catch { ElMessage.error('回测失败') }
  finally { running.value = false }
}

function renderChart() {
  if (!chartRef.value || !result.value) return
  if (!chartInstance.value) {
    chartInstance.value = echarts.init(chartRef.value)
  }
  const d = result.value
  const dark = isDark()
  const c = {
    axisLabel: dark ? 'rgba(248,250,252,0.35)' : 'rgba(0,0,0,0.4)',
    splitLine: dark ? 'rgba(248,250,252,0.03)' : 'rgba(0,0,0,0.04)',
    axisLine: dark ? 'rgba(248,250,252,0.06)' : 'rgba(0,0,0,0.06)',
  }

  const dates = d.periods.map(p => p.date)
  // Equity curve: start at 1.0
  const equity: number[] = [1.0]
  for (const p of d.periods) {
    equity.push(equity[equity.length - 1] * (1 + p.avg_return / 100))
  }
  const equityDates = ['起始', ...dates]
  const drawdowns = d.periods.map(p => p.drawdown ?? 0)

  chartInstance.value.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['净值曲线', '回撤'], textStyle: { color: c.axisLabel, fontSize: 10 }, top: 0 },
    grid: [
      { left: '8%', right: '4%', top: '30', height: '55%' },
      { left: '8%', right: '4%', top: '75%', height: '18%' },
    ],
    xAxis: [
      { type: 'category', data: equityDates, gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, axisLine: { lineStyle: { color: c.axisLine } } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false }, axisLine: { lineStyle: { color: c.axisLine } } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'value', gridIndex: 1, max: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
    ],
    series: [
      {
        name: '净值曲线', type: 'line', data: equity, xAxisIndex: 0, yAxisIndex: 0,
        smooth: true, showSymbol: false,
        lineStyle: { width: 2, color: '#a78bfa' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(167,139,250,0.15)' }, { offset: 1, color: 'rgba(167,139,250,0)' }]) },
      },
      {
        name: '回撤', type: 'bar', data: drawdowns, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: 'rgba(239,68,68,0.5)' },
      },
    ],
  }, true)
}

onBeforeUnmount(() => {
  chartInstance.value?.dispose()
})
</script>

<style scoped>
.backtest-view {
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

.font-mono { font-family: 'Fira Code', monospace; }
.text-up { color: #ef4444; }
.text-down { color: #22c55e; }

.config-card {
  margin-bottom: 16px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 20px;
}

.config-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.metrics-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}

.metric-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.chart-card, .table-card {
  margin-bottom: 16px;
  border-radius: 10px;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.equity-chart {
  width: 100%;
  height: 380px;
}
</style>
