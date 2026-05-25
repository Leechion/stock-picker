<template>
  <div class="factor-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">因子分析</h2>
        <span class="page-subtitle">个股多维度因子拆解 · 雷达图可视化</span>
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
      <div class="content-row">
        <!-- Radar -->
        <div class="chart-panel">
          <div class="panel-title">因子雷达图</div>
          <div ref="radarRef" class="radar-chart" :style="{ height: '420px' }"></div>
        </div>

        <!-- Factor Distribution -->
        <div class="info-panel">
          <div class="panel-title">因子分布</div>

          <div class="category-summary">
            <div class="cat-block" v-for="cat in categories" :key="cat.label">
              <div class="cat-header">
                <span class="cat-label">{{ cat.label }}</span>
                <span class="cat-score font-mono">{{ cat.score }}</span>
              </div>
              <el-progress :percentage="cat.score" :color="getScoreColor(cat.score)" :stroke-width="4" :show-text="false" />
            </div>
          </div>

          <div class="factor-list">
            <div v-for="f in factorList" :key="f.id" class="factor-item">
              <div class="factor-row">
                <span class="factor-name">{{ f.factor_name }}</span>
                <span class="factor-value font-mono">{{ f.value?.toFixed?.(4) ?? f.value ?? '--' }}</span>
              </div>
              <el-tag size="small" :type="factorTypeTag(f.factor_type)" effect="plain">
                {{ factorTypeName(f.factor_type) }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- Detail Table -->
      <el-card shadow="never" class="table-card">
        <template #header><span class="panel-title">因子详情</span></template>
        <el-table :data="factorList" border stripe style="width: 100%">
          <el-table-column prop="factor_name" label="因子名称" width="180" />
          <el-table-column prop="value" label="原始值" align="right">
            <template #default="{ row }">
              <span class="font-mono">{{ row.value?.toFixed?.(4) ?? row.value ?? '--' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="factor_type" label="类别" width="120" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="factorTypeTag(row.factor_type)" effect="plain">
                {{ factorTypeName(row.factor_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="计算时间" width="180" align="center">
            <template #default="{ row }">
              {{ row.computed_at ? new Date(row.computed_at).toLocaleString('zh-CN') : '--' }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <el-empty v-else description="输入股票代码并查询因子数据" :image-size="180" />
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getFactors } from '@/api/factors'
import { getScoreColor } from '@/utils/format'
import type { FactorItem } from '@/types'

const loading = ref(false)
const selectedCode = ref('600519')
const factorList = ref<FactorItem[]>([])

const techScore = ref(0)
const fundScore = ref(0)
const sentScore = ref(0)

const radarRef = ref<HTMLDivElement>()
const radarInstance = ref<echarts.ECharts>()

const categories = computed(() => [
  { label: '技术面', score: techScore.value },
  { label: '基本面', score: fundScore.value },
  { label: '情绪面', score: sentScore.value },
])

function factorTypeName(type: string): string {
  const map: Record<string, string> = { technical: '技术面', fundamental: '基本面', sentiment: '情绪面' }
  return map[type] || type
}

function factorTypeTag(type: string): string {
  const map: Record<string, string> = { technical: 'primary', fundamental: 'success', sentiment: 'warning' }
  return map[type] || ''
}

async function loadFactors() {
  if (!selectedCode.value) return
  loading.value = true
  try {
    const { data } = await getFactors(selectedCode.value)
    factorList.value = data || []

    const tech = factorList.value.filter((f) => f.factor_type === 'technical')
    const fund = factorList.value.filter((f) => f.factor_type === 'fundamental')
    const sent = factorList.value.filter((f) => f.factor_type === 'sentiment')
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
  if (!radarRef.value || factors.length === 0) return

  if (!radarInstance.value) {
    radarInstance.value = echarts.init(radarRef.value)
  }

  const names = factors.map((f) => f.factor_name)
  const values = factors.map((f) => Math.max(0, Math.min(1, (f.value + 1) / 2)))

  const dark = document.documentElement.classList.contains('dark')
  radarInstance.value.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: names.map((n) => ({ name: n, max: 1 })),
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: dark ? 'rgba(248,250,252,0.4)' : 'rgba(0,0,0,0.45)', fontSize: 11 },
      splitLine: { lineStyle: { color: dark ? 'rgba(248,250,252,0.04)' : 'rgba(0,0,0,0.06)' } },
      splitArea: { areaStyle: { color: dark ? ['rgba(124,58,237,0.03)', 'rgba(124,58,237,0.06)'] : ['rgba(124,58,237,0.02)', 'rgba(124,58,237,0.05)'] } },
      axisLine: { lineStyle: { color: dark ? 'rgba(248,250,252,0.06)' : 'rgba(0,0,0,0.06)' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: values,
        name: '因子值',
        areaStyle: { color: 'rgba(124,58,237,0.15)' },
        lineStyle: { color: '#a78bfa', width: 2 },
        itemStyle: { color: '#a78bfa' },
      }],
    }],
  }, true)
}

function resizeRadar() { radarInstance.value?.resize() }

onMounted(() => {
  window.addEventListener('resize', resizeRadar)
  loadFactors()
})

onBeforeUnmount(() => {
  radarInstance.value?.dispose()
  window.removeEventListener('resize', resizeRadar)
})
</script>

<style scoped>
.factor-view {
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
  align-items: center;
}

.font-mono { font-family: 'Fira Code', monospace; }

.content-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

.chart-panel,
.info-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 20px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 14px;
}

.radar-chart { width: 100%; }

.category-summary {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.cat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.cat-label {
  font-size: 12px;
  color: var(--text-muted);
}

.cat-score {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.factor-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.factor-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--hover-bg);
  border-radius: 8px;
  transition: background 0.15s ease;
}

.factor-item:hover {
  background: var(--bg-card-hover);
}

.factor-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.factor-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.factor-value {
  font-size: 12px;
  color: var(--text-muted);
}

.table-card { border-radius: 10px; }
</style>
