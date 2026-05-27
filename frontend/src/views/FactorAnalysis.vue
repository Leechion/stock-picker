<template>
  <div class="factor-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">因子分析</h2>
        <template v-if="stockName">
          <span class="stock-sep">·</span>
          <span class="stock-name">{{ stockName }}</span>
          <span class="stock-code font-mono">{{ selectedCode }}</span>
        </template>
      </div>
      <div class="header-actions">
        <el-input
          v-model="selectedCode"
          placeholder="输入股票代码"
          size="default"
          style="width: 180px"
          @keydown.enter="loadFactors"
        />
        <el-button type="primary" :loading="loading" @click="loadFactors">查询</el-button>
      </div>
    </div>

    <template v-if="factorList.length > 0">
      <!-- Score Cards -->
      <div class="score-row">
        <div class="score-card" v-for="cat in categories" :key="cat.label">
          <div class="sc-header">
            <span class="sc-label">{{ cat.label }}</span>
            <span class="sc-badge" :style="{ background: getLevelBg(cat.level), color: getLevelColor(cat.level) }">{{ cat.level }}</span>
          </div>
          <div class="sc-score">
            <span class="sc-num font-mono" :style="{ color: getScoreColor(cat.score) }">{{ cat.score.toFixed(0) }}</span>
            <span class="sc-max">/100</span>
          </div>
          <div class="sc-bar-track">
            <div class="sc-bar-fill" :style="{ width: cat.score + '%', background: getScoreColor(cat.score) }"></div>
          </div>
          <div class="sc-desc">{{ cat.desc }}</div>
        </div>
      </div>

      <!-- Radar + Factor List -->
      <div class="content-row">
        <div class="chart-panel">
          <div class="panel-title">因子雷达图</div>
          <div class="panel-hint">越靠外越强，看各维度是否均衡</div>
          <div ref="radarRef" class="radar-chart"></div>
        </div>
        <div class="factor-panel">
          <div class="panel-title">因子明细</div>
          <div class="panel-hint">每个因子的评分和含义解读</div>
          <div class="factor-cards">
            <div v-for="f in enrichedFactors" :key="f.id" class="factor-card">
              <div class="fc-header">
                <span class="fc-name">{{ f.cnName }}</span>
                <div class="fc-right">
                  <span class="fc-num font-mono" :style="{ color: getScoreColor(f.normalized) }">{{ f.normalized.toFixed(0) }}</span>
                  <span class="fc-badge" :style="{ color: getLevelColor(f.level) }">{{ f.level }}</span>
                </div>
              </div>
              <div class="fc-bar-track">
                <div class="fc-bar-fill" :style="{ width: f.normalized + '%', background: getScoreColor(f.normalized) }"></div>
              </div>
              <div class="fc-desc">{{ f.desc }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Detail Table -->
      <div class="table-panel">
        <div class="panel-title">因子原始数据</div>
        <el-table :data="enrichedFactors" border stripe size="small" style="width: 100%">
          <el-table-column prop="cnName" label="因子" width="150" />
          <el-table-column prop="factor_type" label="类别" width="100" align="center">
            <template #default="{ row }">
              <span class="type-tag" :class="'type-' + row.factor_type">{{ factorTypeName(row.factor_type) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="评分" width="100" align="center">
            <template #default="{ row }">
              <span class="font-mono" :style="{ color: getScoreColor(row.normalized) }">{{ row.normalized.toFixed(0) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="评价" width="80" align="center">
            <template #default="{ row }">
              <span :style="{ color: getLevelColor(row.level) }">{{ row.level }}</span>
            </template>
          </el-table-column>
          <el-table-column label="含义">
            <template #default="{ row }">
              <span class="desc-cell">{{ row.desc }}</span>
            </template>
          </el-table-column>
          <el-table-column label="原始值" width="100" align="right">
            <template #default="{ row }">
              <span class="font-mono raw-val">{{ row.value?.toFixed?.(4) ?? '--' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <el-empty v-else-if="!loading" description="输入股票代码并查询因子数据" :image-size="180" />
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getFactors } from '@/api/factors'
import { getStockInfo } from '@/api/stocks'
import { getScoreColor } from '@/utils/format'
import type { FactorItem } from '@/types'

const loading = ref(false)
const selectedCode = ref('600519')
const stockName = ref('')
const factorList = ref<FactorItem[]>([])

const techScore = ref(0)
const fundScore = ref(0)
const sentScore = ref(0)

const radarRef = ref<HTMLDivElement>()
const radarInstance = ref<echarts.ECharts>()

const factorMeta: Record<string, { cn: string; desc: string }> = {
  ma_crossover: { cn: '均线交叉', desc: '短期均线上穿长期均线，表明上涨趋势形成' },
  macd: { cn: 'MACD动量', desc: '价格动量指标，正值越大上涨动能越强' },
  rsi: { cn: 'RSI超买超卖', desc: '衡量涨跌力度，>70偏超买，<30偏超卖' },
  kdj: { cn: 'KDJ随机指标', desc: '判断短期买卖时机，>80偏高，<20偏低' },
  bollinger: { cn: '布林带位置', desc: '价格在布林带中的相对位置，越靠近上轨越强势' },
  volume_ratio: { cn: '量比', desc: '当前成交量与均量的比值，>1表示放量' },
  pe_score: { cn: 'PE估值', desc: '市盈率评分，分数越高估值越合理' },
  pb_score: { cn: 'PB估值', desc: '市净率评分，分数越高估值越合理' },
  roe_score: { cn: '盈利能力(ROE)', desc: '净资产收益率评分，越高说明赚钱能力越强' },
  revenue_growth_score: { cn: '营收增长', desc: '营业收入增速评分，越高增长越快' },
  profit_growth_score: { cn: '利润增长', desc: '净利润增速评分，越高盈利增长越快' },
  debt_ratio_score: { cn: '负债健康度', desc: '资产负债率评分，分数越高负债越安全' },
  turnover_score: { cn: '换手率', desc: '股票交易活跃度，适中最好' },
  capital_flow_score: { cn: '资金流向', desc: '主力资金流入情况，正值越大资金越看好' },
  real_capital_flow_score: { cn: '真实资金流', desc: '剔除噪音后的资金动向，更可靠' },
  chip_concentration_score: { cn: '筹码集中度', desc: '筹码集中程度，越高说明主力控盘越强' },
  sector_heat_score: { cn: '板块热度', desc: '所属行业的整体热度，越高板块越活跃' },
  momentum_5d_score: { cn: '5日动量', desc: '近5个交易日的涨势，正值越大短期越强势' },
  momentum_20d_score: { cn: '20日动量', desc: '近20个交易日的涨势，正值越大中期越强势' },
}

function getFactorCnName(name: string): string { return factorMeta[name]?.cn || name }
function getFactorDesc(name: string): string { return factorMeta[name]?.desc || '' }

function getLevel(score: number): string {
  if (score >= 80) return '很强'
  if (score >= 65) return '较强'
  if (score >= 45) return '一般'
  if (score >= 30) return '较弱'
  return '很弱'
}

function getLevelColor(level: string): string {
  return { '很强': '#22c55e', '较强': '#3b82f6', '一般': '#f59e0b', '较弱': '#f97316', '很弱': '#ef4444' }[level] || '#888'
}

function getLevelBg(level: string): string {
  return { '很强': 'rgba(34,197,94,0.12)', '较强': 'rgba(59,130,246,0.12)', '一般': 'rgba(245,158,11,0.12)', '较弱': 'rgba(249,115,22,0.12)', '很弱': 'rgba(239,68,68,0.12)' }[level] || 'rgba(136,136,136,0.12)'
}

const categories = computed(() => [
  { label: '技术面', score: techScore.value, level: getLevel(techScore.value), desc: getCatDesc('tech', techScore.value) },
  { label: '基本面', score: fundScore.value, level: getLevel(fundScore.value), desc: getCatDesc('fund', fundScore.value) },
  { label: '情绪面', score: sentScore.value, level: getLevel(sentScore.value), desc: getCatDesc('sent', sentScore.value) },
])

function getCatDesc(cat: string, score: number): string {
  if (cat === 'tech') return score >= 65 ? '技术形态良好，均线、动量指标偏多' : score >= 45 ? '技术指标中性，无明显趋势' : '技术面偏弱，注意下跌风险'
  if (cat === 'fund') return score >= 65 ? '估值合理，盈利能力和成长性较好' : score >= 45 ? '基本面一般，估值和成长性中等' : '基本面偏弱，估值或盈利需关注'
  return score >= 65 ? '资金流入积极，市场关注度高' : score >= 45 ? '资金面中性，关注度一般' : '资金流出，市场热度较低'
}

const enrichedFactors = computed(() => {
  return factorList.value.map(f => {
    const normalized = Math.max(0, Math.min(100, ((f.value + 1) / 2) * 100))
    return { ...f, cnName: getFactorCnName(f.factor_name), desc: getFactorDesc(f.factor_name), normalized, level: getLevel(normalized) }
  })
})

function factorTypeName(type: string): string {
  return { technical: '技术面', fundamental: '基本面', sentiment: '情绪面' }[type] || type
}

async function loadFactors() {
  if (!selectedCode.value) return
  loading.value = true
  stockName.value = ''
  try {
    getStockInfo(selectedCode.value).then(res => {
      stockName.value = (res.data?.name as string) || ''
    }).catch(() => {})
    const { data } = await getFactors(selectedCode.value)
    factorList.value = data || []
    const tech = factorList.value.filter(f => f.factor_type === 'technical')
    const fund = factorList.value.filter(f => f.factor_type === 'fundamental')
    const sent = factorList.value.filter(f => f.factor_type === 'sentiment')
    const avg = (list: FactorItem[]) => list.length ? list.reduce((s, f) => s + f.value, 0) / list.length : 0
    techScore.value = Math.max(0, Math.min(100, ((avg(tech) + 1) / 2) * 100))
    fundScore.value = Math.max(0, Math.min(100, ((avg(fund) + 1) / 2) * 100))
    sentScore.value = Math.max(0, Math.min(100, ((avg(sent) + 1) / 2) * 100))
    await nextTick()
    renderRadar(factorList.value)
  } catch { factorList.value = [] }
  finally { loading.value = false }
}

function renderRadar(factors: FactorItem[]) {
  if (!radarRef.value || !factors.length) return
  if (!radarInstance.value) radarInstance.value = echarts.init(radarRef.value)
  const names = factors.map(f => getFactorCnName(f.factor_name))
  const values = factors.map(f => Math.max(0, Math.min(1, (f.value + 1) / 2)))
  const dark = document.documentElement.classList.contains('dark')
  radarInstance.value.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (params: { value: number[] }) => factors.map((f, i) => {
        const v = params.value[i]; return `${getFactorCnName(f.factor_name)}: ${(v * 100).toFixed(0)}分 (${getLevel(v * 100)})`
      }).join('<br/>'),
    },
    radar: {
      indicator: names.map(n => ({ name: n, max: 1 })),
      shape: 'polygon', splitNumber: 4,
      axisName: { color: dark ? 'rgba(248,250,252,0.5)' : 'rgba(0,0,0,0.5)', fontSize: 11 },
      splitLine: { lineStyle: { color: dark ? 'rgba(248,250,252,0.04)' : 'rgba(0,0,0,0.06)' } },
      splitArea: { areaStyle: { color: dark ? ['rgba(124,58,237,0.03)', 'rgba(124,58,237,0.06)'] : ['rgba(124,58,237,0.02)', 'rgba(124,58,237,0.05)'] } },
      axisLine: { lineStyle: { color: dark ? 'rgba(248,250,252,0.06)' : 'rgba(0,0,0,0.06)' } },
    },
    series: [{ type: 'radar', data: [{ value: values, name: '因子评分', areaStyle: { color: 'rgba(124,58,237,0.15)' }, lineStyle: { color: '#a78bfa', width: 2 }, itemStyle: { color: '#a78bfa' } }] }],
  }, true)
}

function resizeRadar() { radarInstance.value?.resize() }

onMounted(() => { window.addEventListener('resize', resizeRadar); loadFactors() })
onBeforeUnmount(() => { radarInstance.value?.dispose(); window.removeEventListener('resize', resizeRadar) })
</script>

<style scoped>
.factor-view { max-width: 1400px; margin: 0 auto; }

.page-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;
}
.page-title-group { display: flex; align-items: baseline; gap: 10px; }
.page-title { margin: 0; font-size: 22px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.02em; }
.stock-sep { font-size: 20px; color: var(--text-muted); font-weight: 300; }
.stock-name { font-size: 20px; font-weight: 600; color: var(--text-primary); }
.stock-code { font-size: 13px; color: var(--text-muted); }
.header-actions { display: flex; gap: 8px; align-items: center; }
.font-mono { font-family: 'Fira Code', monospace; }

/* Score Cards */
.score-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 14px; }
.score-card {
  background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 12px;
  padding: 18px 20px; transition: transform 0.15s ease;
}
.score-card:hover { transform: translateY(-1px); }
.sc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.sc-label { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.sc-badge { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; }
.sc-score { margin-bottom: 10px; }
.sc-num { font-size: 32px; font-weight: 700; line-height: 1; }
.sc-max { font-size: 13px; color: var(--text-muted); margin-left: 2px; }
.sc-bar-track { height: 5px; background: var(--hover-bg); border-radius: 3px; overflow: hidden; margin-bottom: 10px; }
.sc-bar-fill { height: 100%; border-radius: 3px; transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1); }
.sc-desc { font-size: 12px; color: var(--text-muted); line-height: 1.5; }

/* Content Row */
.content-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
.chart-panel, .factor-panel {
  background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 12px; padding: 20px;
}
.panel-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.panel-hint { font-size: 11px; color: var(--text-muted); margin-bottom: 14px; }
.radar-chart { width: 100%; height: 380px; }

/* Factor Cards */
.factor-cards { display: flex; flex-direction: column; gap: 8px; max-height: 400px; overflow-y: auto; }
.factor-cards::-webkit-scrollbar { width: 4px; }
.factor-cards::-webkit-scrollbar-thumb { background: var(--border-card); border-radius: 2px; }
.factor-card { padding: 12px 14px; background: var(--hover-bg); border-radius: 8px; transition: background 0.15s ease; }
.factor-card:hover { background: var(--bg-card-hover); }
.fc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.fc-name { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.fc-right { display: flex; align-items: center; gap: 8px; }
.fc-num { font-size: 14px; font-weight: 700; }
.fc-badge { font-size: 11px; font-weight: 600; }
.fc-bar-track { height: 4px; background: var(--bg-card); border-radius: 2px; overflow: hidden; margin-bottom: 6px; }
.fc-bar-fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
.fc-desc { font-size: 11px; color: var(--text-muted); line-height: 1.4; }

/* Table */
.table-panel { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 12px; padding: 20px; }
.table-panel .panel-title { margin-bottom: 14px; }
.type-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.type-technical { background: rgba(99,102,241,0.12); color: #818cf8; }
.type-fundamental { background: rgba(34,197,94,0.12); color: #4ade80; }
.type-sentiment { background: rgba(245,158,11,0.12); color: #fbbf24; }
.desc-cell { font-size: 12px; color: var(--text-secondary); }
.raw-val { font-size: 11px; color: var(--text-muted); }
</style>
