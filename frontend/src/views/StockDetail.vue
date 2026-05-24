<template>
  <div class="detail-view" v-loading="loading">
    <div v-if="!detail" class="empty-state">
      <el-empty description="未找到股票信息" />
    </div>

    <template v-else>
      <!-- Header -->
      <div class="detail-header">
        <div class="header-left">
          <el-button text @click="router.back()" class="back-btn">
            <el-icon><ArrowLeft /></el-icon>
            返回
          </el-button>
          <div class="stock-identity">
            <span class="stock-name">{{ detail.name }}</span>
            <span class="stock-code font-mono">{{ detail.code }}</span>
            <el-tag v-if="detail.industry" size="small" effect="plain" round>{{ detail.industry }}</el-tag>
          </div>
        </div>
        <div class="header-right" v-if="latestData">
          <span v-if="realtimeQuote" class="live-dot"></span>
          <span class="current-price font-mono" :class="priceClass">{{ latestData.close?.toFixed(2) }}</span>
          <span class="price-change" :class="priceClass">{{ formatChangePct(latestData.change_pct) }}</span>
        </div>
      </div>

      <!-- Stats -->
      <div class="stat-row" v-if="latestData">
        <div class="stat-item" v-for="stat in priceStats" :key="stat.label">
          <div class="stat-label">{{ stat.label }}</div>
          <div class="stat-value font-mono" :class="stat.colorClass || ''">{{ stat.value }}</div>
        </div>
      </div>

      <!-- Left Panel + Chart -->
      <div class="content-row">
        <!-- Left Panel -->
        <div class="left-panel">
          <!-- Score -->
          <div class="panel-section">
            <div class="section-title">综合评分</div>
            <div v-if="ranking" class="score-content">
              <div class="total-score">
                <span class="score-number font-mono" :style="{ color: getScoreColor(ranking.score) }">
                  {{ ranking.score?.toFixed(1) }}
                </span>
                <span class="score-rank">#{{ ranking.rank }}</span>
              </div>
              <div class="score-breakdown">
                <div class="breakdown-item" v-for="item in scoreBreakdown" :key="item.label">
                  <div class="breakdown-header">
                    <span class="breakdown-label">{{ item.label }}</span>
                    <span class="breakdown-value font-mono">{{ item.value }}</span>
                  </div>
                  <el-progress
                    :percentage="Math.min(100, Math.max(0, item.score))"
                    :color="getScoreColor(item.score)"
                    :stroke-width="4"
                    :show-text="false"
                  />
                </div>
              </div>
            </div>
            <div v-else class="empty-section">暂无评分</div>
          </div>

          <!-- Fundamentals -->
          <div class="panel-section">
            <div class="section-title">基本面</div>
            <div v-if="fundamentals" class="fund-grid">
              <div class="fund-item" v-for="f in fundItems" :key="f.label">
                <span class="fund-label">{{ f.label }}</span>
                <span class="fund-value font-mono" :class="f.colorClass || ''">{{ f.value }}</span>
              </div>
            </div>
            <div v-else class="empty-section">暂无数据</div>
          </div>

          <!-- Factor Breakdown -->
          <div class="panel-section">
            <div class="section-title">因子明细</div>
            <div v-if="factorGroups.technical.length" class="factor-groups">
              <div class="factor-group" v-for="group in factorGroupList" :key="group.name">
                <div class="group-label">{{ group.label }}</div>
                <div class="factor-row" v-for="f in group.items" :key="f.name">
                  <span class="factor-name">{{ factorNameMap[f.name] || f.name }}</span>
                  <span class="factor-val font-mono" :style="{ color: getScoreColor((f.value + 1) * 50) }">
                    {{ f.value?.toFixed(3) }}
                  </span>
                </div>
              </div>
            </div>
            <div v-else class="empty-section">暂无因子数据</div>
          </div>
        </div>

        <!-- Chart -->
        <div class="chart-panel">
          <div class="panel-header">
            <div class="chart-controls">
              <el-radio-group v-model="chartDays" size="small" @change="onChartRangeChange">
                <el-radio-button :value="0">分时</el-radio-button>
                <el-radio-button :value="30">1月</el-radio-button>
                <el-radio-button :value="90">3月</el-radio-button>
                <el-radio-button :value="180">半年</el-radio-button>
                <el-radio-button :value="250">1年</el-radio-button>
              </el-radio-group>
              <div class="indicator-btns">
                <el-check-tag
                  v-for="ind in indicatorOptions"
                  :key="ind.key"
                  :checked="activeIndicator === ind.key"
                  @change="toggleIndicator(ind.key)"
                  size="small"
                >
                  {{ ind.label }}
                </el-check-tag>
              </div>
            </div>
          </div>
          <div ref="chartRef" class="kline-chart" :style="{ height: chartHeight + 'px' }"></div>
        </div>
      </div>

      <!-- History Table -->
      <el-card shadow="never" class="table-card">
        <template #header>
          <span class="panel-title">历史行情</span>
        </template>
        <el-table :data="history" border stripe style="width: 100%"
          :default-sort="{ prop: 'trade_date', order: 'descending' }">
          <el-table-column prop="trade_date" label="日期" width="120" align="center" sortable />
          <el-table-column prop="open" label="开盘" width="100" align="right">
            <template #default="{ row }"><span class="font-mono">{{ row.open?.toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column prop="close" label="收盘" width="100" align="right">
            <template #default="{ row }">
              <span class="font-mono" :class="row.close >= row.open ? 'text-up' : 'text-down'">{{ row.close?.toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="high" label="最高" width="100" align="right">
            <template #default="{ row }"><span class="font-mono text-up">{{ row.high?.toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column prop="low" label="最低" width="100" align="right">
            <template #default="{ row }"><span class="font-mono text-down">{{ row.low?.toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column prop="volume" label="成交量" width="120" align="right">
            <template #default="{ row }"><span class="font-mono">{{ formatVolume(row.volume) }}</span></template>
          </el-table-column>
          <el-table-column prop="amount" label="成交额" width="120" align="right">
            <template #default="{ row }"><span class="font-mono">{{ formatTurnover(row.amount) }}</span></template>
          </el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="110" align="right" sortable>
            <template #default="{ row }">
              <span class="font-mono" :class="(row.change_pct ?? 0) >= 0 ? 'text-up' : 'text-down'">
                {{ formatChangePct(row.change_pct) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { useStocksStore } from '@/store'
import { getStockHistory, getStockInfo, getStockFundamentals } from '@/api/stocks'
import { getStockRank } from '@/api/ranking'
import { getActiveStrategy } from '@/api/strategy'
import { getFactors } from '@/api/factors'
import { formatChangePct, formatVolume, formatTurnover, getScoreColor } from '@/utils/format'
import type { StockHistory, RankingItem } from '@/types'

const route = useRoute()
const router = useRouter()
const store = useStocksStore()

const loading = ref(true)
const chartRef = ref<HTMLDivElement>()
const chartInstance = ref<echarts.ECharts>()
const chartDays = ref(90)
const chartHeight = ref(450)
const ranking = ref<RankingItem | null>(null)
const fundamentals = ref<Record<string, number | null> | null>(null)
const factorGroups = ref<{ technical: { name: string; value: number }[]; fundamental: { name: string; value: number }[]; sentiment: { name: string; value: number }[] }>({ technical: [], fundamental: [], sentiment: [] })
const activeIndicator = ref('')
const realtimeQuote = ref<Record<string, number | null> | null>(null)
const refreshTimer = ref<number | null>(null)

function isDark() {
  return document.documentElement.classList.contains('dark')
}

function chartColors() {
  const dark = isDark()
  return {
    axisLine: dark ? 'rgba(248,250,252,0.06)' : 'rgba(0,0,0,0.06)',
    axisLabel: dark ? 'rgba(248,250,252,0.35)' : 'rgba(0,0,0,0.4)',
    splitLine: dark ? 'rgba(248,250,252,0.03)' : 'rgba(0,0,0,0.04)',
    tooltipBorder: dark ? 'rgba(248,250,252,0.04)' : 'rgba(0,0,0,0.06)',
    tooltipBg: dark ? 'rgba(248,250,252,0.02)' : 'rgba(255,255,255,0.96)',
    tooltipText: dark ? 'rgba(248,250,252,0.35)' : 'rgba(0,0,0,0.6)',
    legendText: dark ? 'rgba(248,250,252,0.4)' : 'rgba(0,0,0,0.45)',
    emptyText: dark ? 'rgba(248,250,252,0.3)' : 'rgba(0,0,0,0.3)',
    markLine: dark ? 'rgba(248,250,252,0.15)' : 'rgba(0,0,0,0.1)',
    markLabel: dark ? 'rgba(248,250,252,0.3)' : 'rgba(0,0,0,0.35)',
  }
}

const indicatorOptions = [
  { key: 'macd', label: 'MACD' },
  { key: 'rsi', label: 'RSI' },
  { key: 'kdj', label: 'KDJ' },
]

const factorNameMap: Record<string, string> = {
  ma_crossover: '均线交叉', macd: 'MACD', rsi: 'RSI', kdj: 'KDJ', bollinger: '布林带', volume_ratio: '量比',
  pe_score: 'PE评分', pb_score: 'PB评分', roe_score: 'ROE评分',
  revenue_growth_score: '营收增长', profit_growth_score: '利润增长', debt_ratio_score: '负债率',
  turnover_score: '换手率', capital_flow_score: '资金流', real_capital_flow_score: '真实资金流',
  chip_concentration_score: '筹码集中', sector_heat_score: '板块热度',
  momentum_5d_score: '5日动量', momentum_20d_score: '20日动量',
}

const code = computed(() => String(route.params.code))
const detail = computed(() => store.stockDetail)
const history = computed(() => store.stockHistory)
const latestData = computed(() => {
  const q = realtimeQuote.value
  if (q && q.price != null) {
    return {
      open: q.open ?? 0,
      close: q.price as number,
      high: q.high ?? 0,
      low: q.low ?? 0,
      volume: (q.volume as number) ?? 0,
      amount: (q.amount as number) ?? 0,
      change_pct: q.change_pct ?? 0,
    }
  }
  return history.value.length ? history.value[history.value.length - 1] : null
})

const priceClass = computed(() => {
  if (!latestData.value) return ''
  return (latestData.value.change_pct ?? 0) >= 0 ? 'text-up' : 'text-down'
})

const priceStats = computed(() => {
  const d = latestData.value
  if (!d) return []
  const isRealtime = realtimeQuote.value != null
  return [
    { label: '开盘', value: d.open?.toFixed(2) },
    { label: isRealtime ? '现价' : '收盘', value: d.close?.toFixed(2) },
    { label: '最高', value: d.high?.toFixed(2), colorClass: 'text-up' },
    { label: '最低', value: d.low?.toFixed(2), colorClass: 'text-down' },
    { label: '成交量', value: formatVolume(d.volume) },
    { label: '成交额', value: formatTurnover(d.amount) },
  ]
})

const scoreBreakdown = computed(() => {
  if (!ranking.value) return []
  return [
    { label: '技术面', score: ranking.value.tech_score ?? 0, value: (ranking.value.tech_score ?? 0).toFixed(1) },
    { label: '基本面', score: ranking.value.fund_score ?? 0, value: (ranking.value.fund_score ?? 0).toFixed(1) },
    { label: '情绪面', score: ranking.value.sent_score ?? 0, value: (ranking.value.sent_score ?? 0).toFixed(1) },
  ]
})

const fundItems = computed(() => {
  const f = fundamentals.value
  if (!f) return []
  const pct = (v: number | null) => v != null ? v.toFixed(1) + '%' : '--'
  const num = (v: number | null) => v != null ? v.toFixed(2) : '--'
  const growthColor = (v: number | null) => v == null ? '' : v >= 0 ? 'text-up' : 'text-down'
  return [
    { label: 'PE(TTM)', value: num(f.pe_ttm) },
    { label: 'PB', value: num(f.pb) },
    { label: 'ROE', value: pct(f.roe), colorClass: (f.roe ?? 0) >= 0 ? 'text-up' : 'text-down' },
    { label: '营收增长', value: pct(f.revenue_growth), colorClass: growthColor(f.revenue_growth) },
    { label: '利润增长', value: pct(f.profit_growth), colorClass: growthColor(f.profit_growth) },
    { label: '资产负债率', value: pct(f.debt_ratio) },
  ]
})

const factorGroupList = computed(() => {
  const g = factorGroups.value
  return [
    { name: 'technical', label: '技术面', items: g.technical },
    { name: 'fundamental', label: '基本面', items: g.fundamental },
    { name: 'sentiment', label: '情绪面', items: g.sentiment },
  ].filter(g => g.items.length > 0)
})

// --- Technical Indicator Calculations ---

function calcMA(prices: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < prices.length; i++) {
    if (i < period - 1) { result.push(null); continue }
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += prices[j]
    result.push(sum / period)
  }
  return result
}

function calcEMA(prices: number[], period: number): number[] {
  const k = 2 / (period + 1)
  const result: number[] = [prices[0]]
  for (let i = 1; i < prices.length; i++) {
    result.push(prices[i] * k + result[i - 1] * (1 - k))
  }
  return result
}

function calcMACD(closes: number[]) {
  const ema12 = calcEMA(closes, 12)
  const ema26 = calcEMA(closes, 26)
  const dif = ema12.map((v, i) => v - ema26[i])
  const dea = calcEMA(dif, 9)
  const macd = dif.map((v, i) => (v - dea[i]) * 2)
  return { dif, dea, macd }
}

function calcRSI(closes: number[], period: number = 14): number[] {
  const result: number[] = []
  let gainSum = 0, lossSum = 0
  for (let i = 0; i < closes.length; i++) {
    if (i === 0) { result.push(50); continue }
    const change = closes[i] - closes[i - 1]
    if (i < period) {
      gainSum += Math.max(0, change)
      lossSum += Math.max(0, -change)
      result.push(50)
      continue
    }
    if (i === period) {
      gainSum += Math.max(0, change)
      lossSum += Math.max(0, -change)
    } else {
      gainSum = gainSum * (period - 1) / period + Math.max(0, change)
      lossSum = lossSum * (period - 1) / period + Math.max(0, -change)
    }
    if (lossSum === 0) { result.push(100); continue }
    result.push(100 - 100 / (1 + gainSum / lossSum))
  }
  return result
}

function calcKDJ(highs: number[], lows: number[], closes: number[], n: number = 9) {
  const kArr: number[] = [], dArr: number[] = [], jArr: number[] = []
  let prevK = 50, prevD = 50
  for (let i = 0; i < closes.length; i++) {
    if (i < n - 1) { kArr.push(50); dArr.push(50); jArr.push(50); continue }
    let hn = -Infinity, ln = Infinity
    for (let j = i - n + 1; j <= i; j++) {
      hn = Math.max(hn, highs[j])
      ln = Math.min(ln, lows[j])
    }
    const rsv = hn === ln ? 50 : ((closes[i] - ln) / (hn - ln)) * 100
    const k = prevK * 2 / 3 + rsv / 3
    const d = prevD * 2 / 3 + k / 3
    const j = 3 * k - 2 * d
    kArr.push(k); dArr.push(d); jArr.push(j)
    prevK = k; prevD = d
  }
  return { k: kArr, d: dArr, j: jArr }
}

// --- Chart ---

function toggleIndicator(key: string) {
  activeIndicator.value = activeIndicator.value === key ? '' : key
  if (chartDays.value === 0) {
    loadIntraday()
  } else if (history.value.length > 0) {
    renderChart(history.value)
  }
}

function onChartRangeChange(val: number) {
  if (val === 0) {
    loadIntraday()
  } else {
    loadHistory()
  }
}

function resizeChart() {
  const hasIndicator = activeIndicator.value !== ''
  chartHeight.value = hasIndicator
    ? Math.max(450, Math.min(600, window.innerHeight - 350))
    : Math.max(350, Math.min(500, window.innerHeight - 450))
  nextTick(() => chartInstance.value?.resize())
}

function renderChart(data: StockHistory[]) {
  if (!chartInstance.value || data.length === 0) return
  const c = chartColors()

  const dates = data.map((d) => String(d.trade_date))
  const closes = data.map((d) => d.close)
  const highs = data.map((d) => d.high)
  const lows = data.map((d) => d.low)
  const ohlc = data.map((d) => [d.open, d.close, d.low, d.high])
  const volumes = data.map((d) => d.volume)

  const hasIndicator = activeIndicator.value !== ''

  // Grid layout
  const grids: Record<string, unknown>[] = []
  const xAxes: Record<string, unknown>[] = []
  const yAxes: Record<string, unknown>[] = []
  const series: Record<string, unknown>[] = []
  const dataZoomXAxisIdx: number[] = [0]

  if (!hasIndicator) {
    // Simple: K-line + Volume
    grids.push(
      { left: '6%', right: '3%', top: '4%', height: '70%' },
      { left: '6%', right: '3%', top: '80%', height: '12%' },
    )
    xAxes.push(
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true, axisLine: { lineStyle: { color: c.axisLine } }, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true, axisLine: { lineStyle: { color: c.axisLine } }, axisLabel: { show: false }, splitLine: { show: false } },
    )
    yAxes.push(
      { scale: true, gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } }, splitArea: { show: false } },
      { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    )
    dataZoomXAxisIdx.push(1)
    series.push(
      { name: 'K线', type: 'candlestick', data: ohlc, itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' } },
      { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: (params: unknown) => { const idx = (params as { dataIndex: number }).dataIndex; const item = data[idx]; return item && item.close >= item.open ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)' } } },
    )
  } else {
    // K-line + Indicator + Volume
    grids.push(
      { left: '6%', right: '3%', top: '3%', height: '45%' },
      { left: '6%', right: '3%', top: '53%', height: '22%' },
      { left: '6%', right: '3%', top: '80%', height: '12%' },
    )
    xAxes.push(
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true, axisLine: { lineStyle: { color: c.axisLine } }, axisLabel: { show: false }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true, axisLine: { lineStyle: { color: c.axisLine } }, axisLabel: { show: false }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: dates, gridIndex: 2, boundaryGap: true, axisLine: { lineStyle: { color: c.axisLine } }, axisLabel: { show: false }, splitLine: { show: false } },
    )
    yAxes.push(
      { scale: true, gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { scale: true, gridIndex: 1, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    )
    dataZoomXAxisIdx.push(1, 2)

    // K-line + MA overlays
    series.push(
      { name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0, itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' } },
    )

    // MA lines
    const maColors: Record<number, string> = { 5: '#f59e0b', 10: '#a78bfa', 20: '#3b82f6', 60: '#ef4444' }
    for (const period of [5, 10, 20, 60]) {
      const ma = calcMA(closes, period)
      series.push({
        name: `MA${period}`, type: 'line', data: ma, xAxisIndex: 0, yAxisIndex: 0,
        smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[period] },
      })
    }

    // Indicator sub-chart
    if (activeIndicator.value === 'macd') {
      const { dif, dea, macd } = calcMACD(closes)
      series.push(
        { name: 'DIF', type: 'line', data: dif, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#a78bfa' } },
        { name: 'DEA', type: 'line', data: dea, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
        { name: 'MACD', type: 'bar', data: macd, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: (params: unknown) => { const v = (params as { data: number }).data; return v >= 0 ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)' } } },
      )
    } else if (activeIndicator.value === 'rsi') {
      const rsi = calcRSI(closes)
      series.push(
        { name: 'RSI(14)', type: 'line', data: rsi, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1.5, color: '#a78bfa' } },
      )
    } else if (activeIndicator.value === 'kdj') {
      const { k, d, j } = calcKDJ(highs, lows, closes)
      series.push(
        { name: 'K', type: 'line', data: k, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#a78bfa' } },
        { name: 'D', type: 'line', data: d, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
        { name: 'J', type: 'line', data: j, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } },
      )
    }

    // Volume
    series.push(
      { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 2, yAxisIndex: 2, itemStyle: { color: (params: unknown) => { const idx = (params as { dataIndex: number }).dataIndex; const item = data[idx]; return item && item.close >= item.open ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)' } } },
    )
  }

  const option: echarts.EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { show: hasIndicator, top: 0, textStyle: { color: c.legendText, fontSize: 10 } },
    grid: grids as echarts.EChartsOption['grid'],
    xAxis: xAxes as echarts.EChartsOption['xAxis'],
    yAxis: yAxes as echarts.EChartsOption['yAxis'],
    dataZoom: [
      { type: 'inside', xAxisIndex: dataZoomXAxisIdx, start: 0, end: 100 },
      {
        type: 'slider', xAxisIndex: dataZoomXAxisIdx, start: 0, end: 100,
        bottom: 0, height: 24,
        borderColor: c.tooltipBorder,
        fillerColor: 'rgba(124,58,237,0.15)',
        backgroundColor: c.tooltipBg,
        textStyle: { color: c.tooltipText, fontSize: 10 },
        handleStyle: { color: '#a78bfa' },
        dataBackground: { lineStyle: { color: 'rgba(124,58,237,0.3)' }, areaStyle: { color: 'rgba(124,58,237,0.08)' } },
      },
    ],
    series: series as echarts.EChartsOption['series'],
  }

  chartInstance.value.setOption(option, true)
}

// --- Data Loading ---

async function loadStockInfo() {
  try {
    const resp = await getStockInfo(code.value)
    store.setDetail(resp.data)
  } catch { /* handled */ }
}

async function loadRanking() {
  try {
    const { data: stratData } = await getActiveStrategy()
    const resp = await getStockRank(code.value, stratData.slug)
    const r = resp.data || resp
    ranking.value = {
      ...r,
      score: r.total_score ?? r.score,
    }
  } catch { ranking.value = null }
}

async function loadFundamentals() {
  try {
    const resp = await getStockFundamentals(code.value)
    fundamentals.value = resp.data || resp
  } catch { fundamentals.value = null }
}

async function loadFactors() {
  try {
    const resp = await getFactors(code.value)
    const items: Record<string, unknown>[] = Array.isArray(resp.data) ? resp.data : (Array.isArray(resp) ? resp : [])
    const toNameVal = (f: Record<string, unknown>) => ({ name: String(f.factor_name || f.name || ''), value: Number(f.value) })
    factorGroups.value = {
      technical: items.filter((f) => ['ma_crossover','macd','rsi','kdj','bollinger','volume_ratio'].includes(String(f.factor_name || f.name))).map(toNameVal),
      fundamental: items.filter((f) => ['pe_score','pb_score','roe_score','revenue_growth_score','profit_growth_score','debt_ratio_score'].includes(String(f.factor_name || f.name))).map(toNameVal),
      sentiment: items.filter((f) => ['turnover_score','capital_flow_score','momentum_5d_score','momentum_20d_score'].includes(String(f.factor_name || f.name))).map(toNameVal),
    }
  } catch { /* ignore */ }
}

async function loadHistory() {
  loading.value = true
  try {
    const { data } = await getStockHistory(code.value, chartDays.value)
    const records = Array.isArray(data) ? data : []
    store.setHistory(records)
    if (records.length > 0 && chartInstance.value) renderChart(records)
  } catch { store.setHistory([]) }
  finally { loading.value = false }
}

async function loadRealtimeQuote() {
  try {
    const base = localStorage.getItem('apiUrl') || '/api'
    const resp = await fetch(`${base}/stocks/quote?code=${code.value}`)
    const body = await resp.json()
    if (body.code === 0 && body.data) {
      realtimeQuote.value = body.data
    }
  } catch { /* silent */ }
}

function startAutoRefresh() {
  stopAutoRefresh()
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const minutes = h * 60 + m
  const isTrading = (minutes >= 570 && minutes <= 690) || (minutes >= 780 && minutes <= 900)
  if (isTrading) {
    refreshTimer.value = window.setInterval(() => loadRealtimeQuote(), 15000)
  }
}

function stopAutoRefresh() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

async function loadIntraday() {
  loading.value = true
  try {
    const base = localStorage.getItem('apiUrl') || '/api'
    const resp = await fetch(`${base}/stocks/intraday?code=${code.value}&period=1`)
    const body = await resp.json()
    const records = body.code === 0 ? (body.data || []) : []
    if (records.length > 0 && chartInstance.value) {
      renderIntradayChart(records, (realtimeQuote.value?.pre_close as number) ?? Number(records[0].open))
    } else if (chartInstance.value) {
      chartInstance.value.setOption({
        title: { text: '暂无分时数据', left: 'center', top: 'middle',
          textStyle: { color: chartColors().emptyText, fontSize: 14 } },
        xAxis: { show: false }, yAxis: { show: false }, series: [],
      }, true)
    }
  } catch { /* silent */ }
  finally { loading.value = false }
}

function renderIntradayChart(data: Record<string, unknown>[], preClose: number) {
  if (!chartInstance.value || data.length === 0) return
  const c = chartColors()

  const times = data.map(d => String(d.time).split(' ')[1] || String(d.time))
  const closes = data.map(d => Number(d.close))
  const highs = data.map(d => Number(d.high))
  const lows = data.map(d => Number(d.low))
  const volumes = data.map(d => Number(d.volume))

  const hasIndicator = activeIndicator.value !== ''

  // Color: red if last price >= preClose, green otherwise
  const lastClose = closes[closes.length - 1]
  const lineColor = lastClose >= preClose ? '#ef4444' : '#22c55e'
  const areaTop = lastClose >= preClose ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)'
  const areaBottom = lastClose >= preClose ? 'rgba(239,68,68,0)' : 'rgba(34,197,94,0)'

  const grids: Record<string, unknown>[] = []
  const xAxes: Record<string, unknown>[] = []
  const yAxes: Record<string, unknown>[] = []
  const series: Record<string, unknown>[] = []
  const dataZoomIdx: number[] = [0]

  if (!hasIndicator) {
    grids.push(
      { left: '6%', right: '3%', top: '4%', height: '70%' },
      { left: '6%', right: '3%', top: '80%', height: '12%' },
    )
    xAxes.push(
      { type: 'category', data: times, gridIndex: 0, boundaryGap: false, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: times, gridIndex: 1, boundaryGap: false, axisLabel: { show: false }, splitLine: { show: false } },
    )
    yAxes.push(
      { scale: true, gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    )
    dataZoomIdx.push(1)
    series.push(
      { name: '分时', type: 'line', data: closes, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: lineColor }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: areaTop }, { offset: 1, color: areaBottom }]) }, markLine: { silent: true, symbol: 'none', lineStyle: { color: c.markLine, type: 'dashed', width: 1 }, label: { formatter: '昨收 ' + preClose.toFixed(2), color: c.markLabel, fontSize: 10, position: 'insideStartTop' }, data: [{ yAxis: preClose }] } },
      { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: (p: unknown) => { const idx = (p as {dataIndex:number}).dataIndex; const item = data[idx]; return item && Number(item.close) >= Number(item.open) ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)' } } },
    )
  } else {
    grids.push(
      { left: '6%', right: '3%', top: '3%', height: '45%' },
      { left: '6%', right: '3%', top: '53%', height: '22%' },
      { left: '6%', right: '3%', top: '80%', height: '12%' },
    )
    xAxes.push(
      { type: 'category', data: times, gridIndex: 0, boundaryGap: false, axisLabel: { show: false }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: times, gridIndex: 1, boundaryGap: false, axisLabel: { show: false }, splitLine: { lineStyle: { color: c.splitLine } } },
      { type: 'category', data: times, gridIndex: 2, boundaryGap: false, axisLabel: { show: false }, splitLine: { show: false } },
    )
    yAxes.push(
      { scale: true, gridIndex: 0, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { scale: true, gridIndex: 1, axisLabel: { color: c.axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: c.splitLine } } },
      { scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    )
    dataZoomIdx.push(1, 2)

    series.push(
      { name: '分时', type: 'line', data: closes, smooth: true, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1.5, color: lineColor }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: areaTop }, { offset: 1, color: areaBottom }]) }, markLine: { silent: true, symbol: 'none', lineStyle: { color: c.markLine, type: 'dashed', width: 1 }, label: { formatter: '昨收 ' + preClose.toFixed(2), color: c.markLabel, fontSize: 10, position: 'insideStartTop' }, data: [{ yAxis: preClose }] } },
    )

    if (activeIndicator.value === 'macd') {
      const { dif, dea, macd } = calcMACD(closes)
      series.push(
        { name: 'DIF', type: 'line', data: dif, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#a78bfa' } },
        { name: 'DEA', type: 'line', data: dea, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
        { name: 'MACD', type: 'bar', data: macd, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: (p: unknown) => { const v = (p as {data:number}).data; return v >= 0 ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)' } } },
      )
    } else if (activeIndicator.value === 'rsi') {
      const rsi = calcRSI(closes)
      series.push({ name: 'RSI(14)', type: 'line', data: rsi, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1.5, color: '#a78bfa' } })
    } else if (activeIndicator.value === 'kdj') {
      const { k, d, j } = calcKDJ(highs, lows, closes)
      series.push(
        { name: 'K', type: 'line', data: k, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#a78bfa' } },
        { name: 'D', type: 'line', data: d, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
        { name: 'J', type: 'line', data: j, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } },
      )
    }

    series.push(
      { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 2, yAxisIndex: 2, itemStyle: { color: (p: unknown) => { const idx = (p as {dataIndex:number}).dataIndex; const item = data[idx]; return item && Number(item.close) >= Number(item.open) ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)' } } },
    )
  }

  const option: echarts.EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { show: hasIndicator, top: 0, textStyle: { color: c.legendText, fontSize: 10 } },
    grid: grids as echarts.EChartsOption['grid'],
    xAxis: xAxes as echarts.EChartsOption['xAxis'],
    yAxis: yAxes as echarts.EChartsOption['yAxis'],
    dataZoom: [
      { type: 'inside', xAxisIndex: dataZoomIdx, start: 0, end: 100 },
    ],
    series: series as echarts.EChartsOption['series'],
  }

  chartInstance.value.setOption(option, true)
}

function initChart() {
  if (!chartRef.value || chartInstance.value) return
  chartInstance.value = echarts.init(chartRef.value)
  window.addEventListener('resize', resizeChart)
  resizeChart()
}

onMounted(() => {
  loadStockInfo()
  loadRanking()
  loadFundamentals()
  loadFactors()
})

// Watch for detail to load → chart element renders → then init chart + load history
const stopWatch = watch(detail, async (val) => {
  if (!val) return
  await nextTick()
  resizeChart()
  initChart()
  loadRealtimeQuote()
  startAutoRefresh()
  loadHistory()
  stopWatch()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
  chartInstance.value?.dispose()
  window.removeEventListener('resize', resizeChart)
})
</script>

<style scoped>
.detail-view {
  max-width: 1400px;
  margin: 0 auto;
}

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

.font-mono { font-family: 'Fira Code', monospace; }
.text-up { color: #ef4444; }
.text-down { color: #22c55e; }

/* Header */
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 14px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
}

.header-left { display: flex; align-items: center; gap: 14px; }
.stock-identity { display: flex; align-items: center; gap: 10px; }

.stock-name {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.stock-code {
  font-size: 13px;
  color: var(--text-muted);
}

.header-right { display: flex; align-items: baseline; gap: 10px; }
.current-price { font-size: 26px; font-weight: 600; }
.price-change { font-size: 14px; font-weight: 500; }

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse 2s infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Stats */
.stat-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}

.stat-item {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}

.stat-label { font-size: 11px; color: var(--text-muted); margin-bottom: 3px; }
.stat-value { font-size: 15px; font-weight: 600; color: var(--text-primary); }

/* Content Row */
.content-row {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 520px;
  overflow-y: auto;
}

.panel-section,
.chart-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 14px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
  letter-spacing: 0.02em;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.indicator-btns {
  display: flex;
  gap: 4px;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

/* Score */
.score-content { display: flex; flex-direction: column; gap: 12px; }
.total-score { text-align: center; }

.score-number {
  font-size: 32px;
  font-weight: 700;
  display: block;
  line-height: 1;
  margin-bottom: 2px;
}

.score-rank { font-size: 12px; color: var(--text-muted); }
.score-breakdown { display: flex; flex-direction: column; gap: 10px; }
.breakdown-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; }
.breakdown-label { font-size: 12px; color: var(--text-secondary); }
.breakdown-value { font-size: 12px; font-weight: 600; color: var(--text-primary); }

/* Fundamentals */
.fund-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.fund-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  background: var(--hover-bg);
  border-radius: 6px;
}

.fund-label { font-size: 11px; color: var(--text-muted); }
.fund-value { font-size: 12px; font-weight: 600; color: var(--text-primary); }

/* Factor Breakdown */
.factor-groups { display: flex; flex-direction: column; gap: 8px; }
.factor-group {}
.group-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.factor-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}

.factor-name { font-size: 11px; color: var(--text-secondary); }
.factor-val { font-size: 11px; font-weight: 600; }

.empty-section {
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  padding: 10px 0;
}

.kline-chart { width: 100%; min-height: 350px; }
.table-card { border-radius: 10px; }
</style>
