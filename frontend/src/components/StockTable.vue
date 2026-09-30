<template>
  <div class="stock-table-wrapper">
    <el-table
      :data="data"
      :loading="loading"
      stripe
      style="width: 100%"
      @row-click="(row: RankingItem) => emits('rowClick', row)"
      :row-class-name="tableRowClassName"
    >
      <el-table-column type="index" label="排名" width="72" align="center" fixed>
        <template #default="{ row, $index }">
          <span :class="getRankBadgeClass(displayRank(row, $index))">
            {{ displayRank(row, $index) }}
          </span>
        </template>
      </el-table-column>

      <el-table-column prop="code" label="代码" width="100" align="center" fixed>
        <template #default="{ row }">
          <span class="code-text">{{ row.code }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="name" label="名称" min-width="110" />

      <el-table-column prop="industry" label="行业" width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.industry" size="small" effect="plain" :type="getIndustryTagType(row.industry)" round>
            {{ row.industry }}
          </el-tag>
          <span v-else class="text-dim">--</span>
        </template>
      </el-table-column>

      <!-- Realtime columns: values come from the `quotes` WebSocket channel and
           update without any user action. `flash` briefly highlights a cell. -->
      <el-table-column label="现价" width="110" align="right">
        <template #default="{ row }">
          <span
            v-if="quoteFor(row.code)?.price"
            class="live-price"
            :class="[{ 'is-flash': quoteFor(row.code)?.flash }, priceClass(quoteFor(row.code)?.change_pct)]"
          >
            {{ quoteFor(row.code)!.price.toFixed(2) }}
          </span>
          <span v-else class="text-dim">--</span>
        </template>
      </el-table-column>

      <el-table-column label="涨跌幅" width="100" align="right">
        <template #default="{ row }">
          <span
            v-if="quoteFor(row.code)?.change_pct !== undefined"
            class="live-change"
            :class="[{ 'is-flash': quoteFor(row.code)?.flash }, priceClass(quoteFor(row.code)?.change_pct)]"
          >
            {{ formatPct(quoteFor(row.code)!.change_pct) }}
          </span>
          <span v-else class="text-dim">--</span>
        </template>
      </el-table-column>

      <el-table-column label="综合评分" width="140" align="center" sortable :sort-method="(a: RankingItem, b: RankingItem) => (a.score ?? 0) - (b.score ?? 0)">
        <template #default="{ row }">
          <div class="score-cell">
            <span class="score-value" :style="{ color: getScoreColor(row.score) }">
              {{ row.score?.toFixed?.(1) ?? '--' }}
            </span>
            <el-progress
              :percentage="Math.min(100, row.score ?? 0)"
              :color="getScoreColor(row.score)"
              :stroke-width="5"
              :show-text="false"
              class="score-progress"
            />
          </div>
        </template>
      </el-table-column>

      <el-table-column label="技术面" width="90" align="center" sortable :sort-method="(a: RankingItem, b: RankingItem) => (a.tech_score ?? 0) - (b.tech_score ?? 0)">
        <template #default="{ row }">
          <span class="mini-score" :style="{ color: getScoreColor(row.tech_score ?? 0) }">
            {{ row.tech_score?.toFixed?.(1) ?? '--' }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="基本面" width="90" align="center" sortable :sort-method="(a: RankingItem, b: RankingItem) => (a.fund_score ?? 0) - (b.fund_score ?? 0)">
        <template #default="{ row }">
          <span class="mini-score" :style="{ color: getScoreColor(row.fund_score ?? 0) }">
            {{ row.fund_score?.toFixed?.(1) ?? '--' }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="情绪面" width="90" align="center" sortable :sort-method="(a: RankingItem, b: RankingItem) => (a.sent_score ?? 0) - (b.sent_score ?? 0)">
        <template #default="{ row }">
          <span class="mini-score" :style="{ color: getScoreColor(row.sent_score ?? 0) }">
            {{ row.sent_score?.toFixed?.(1) ?? '--' }}
          </span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrapper">
      <el-pagination
        :current-page="currentPage"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        background
        small
        @update:current-page="(page: number) => emits('update:currentPage', page)"
        @update:page-size="(size: number) => emits('update:pageSize', size)"
      />
    </div>
  </div>
</template>

<script lang="ts" setup>
import { computed } from 'vue'
import { getScoreColor, getRankBadgeClass } from '@/utils/format'
import { useLiveQuotes } from '@/composables/useLiveQuotes'
import type { RankingItem } from '@/types'

const props = defineProps<{
  data: RankingItem[]
  total: number
  loading: boolean
  currentPage: number
  pageSize: number
}>()

const emits = defineEmits<{
  rowClick: [row: RankingItem]
  'update:currentPage': [page: number]
  'update:pageSize': [size: number]
}>()

function displayRank(row: RankingItem, index: number): number {
  return row.rank || (props.currentPage - 1) * props.pageSize + index + 1
}

function tableRowClassName({ row }: { row: RankingItem }): string {
  const rank = row.rank || 0
  if (rank >= 1 && rank <= 3) return 'row-top3'
  return ''
}

function getIndustryTagType(industry: string | null | undefined): '' | 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  if (!industry) return 'info'
  const tech = ['半导体', '芯片', '电子设备', '软件', '信息技术', '计算机', '通信']
  const finance = ['银行', '保险', '证券', '金融']
  const healthcare = ['医药', '医疗', '生物', '制药']
  if (tech.some((t) => industry.includes(t))) return 'primary'
  if (finance.some((t) => industry.includes(t))) return 'warning'
  if (healthcare.some((t) => industry.includes(t))) return 'success'
  return 'info'
}

// ----------------------------------------------------------------------
// Realtime prices
// ----------------------------------------------------------------------
// Subscribes to the `quotes` WS channel for whatever codes are on screen.
// The server pushes only codes whose price moved, so this stays cheap even
// though the market has ~3200 tickers.
const visibleCodes = computed(() => props.data.map((r) => r.code))
const { quotes: liveQuotes } = useLiveQuotes(() => visibleCodes.value)

function quoteFor(code: string) {
  return liveQuotes.value.get(code)
}

/** A-share convention: red = up, green = down. */
function priceClass(changePct: number | undefined): string {
  if (changePct === undefined || changePct === null) return ''
  if (changePct > 0) return 'is-up'
  if (changePct < 0) return 'is-down'
  return 'is-flat'
}

function formatPct(v: number): string {
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}
</script>

<style scoped>
.stock-table-wrapper { width: 100%; }

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 16px 0 4px;
  border-top: 1px solid rgba(248, 250, 252, 0.04);
  margin-top: 12px;
}

.score-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.score-value {
  font-size: 15px;
  font-weight: 700;
  font-family: 'Fira Code', monospace;
}

.mini-score {
  font-size: 13px;
  font-weight: 600;
  font-family: 'Fira Code', monospace;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(248, 250, 252, 0.04);
}

.code-text {
  font-family: 'Fira Code', monospace;
  font-weight: 500;
  font-size: 13px;
}

/* Realtime quote cells ------------------------------------------------- */
.live-price,
.live-change {
  font-family: 'Fira Code', monospace;
  font-weight: 600;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background-color 0.45s ease;
}

.live-price.is-up,
.live-change.is-up { color: #f56c6c; }
.live-price.is-down,
.live-change.is-down { color: #67c23a; }
.live-price.is-flat,
.live-change.is-flat { color: #909399; }

/* Brief highlight when a tick arrives, so movement is noticeable. */
.live-price.is-flash,
.live-change.is-flash {
  background-color: rgba(64, 158, 255, 0.22);
}

.text-dim { color: rgba(248, 250, 252, 0.2); }

:deep(.row-top3 td) {
  background-color: rgba(124, 58, 237, 0.06) !important;
}

:deep(.row-top3 td:first-child) {
  box-shadow: inset 3px 0 0 #a78bfa;
}

:deep(.el-table__row) {
  cursor: pointer;
  transition: background 0.15s;
  animation: rowFadeIn 0.3s ease both;
}

@keyframes rowFadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

:deep(.el-table__row:hover td) {
  background-color: rgba(124, 58, 237, 0.05) !important;
}

.badge-rank-1 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: linear-gradient(135deg, #ffd700, #f59e0b);
  color: #fff;
  font-weight: 700;
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
}

.badge-rank-2 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.25), rgba(148, 163, 184, 0.12));
  color: rgba(248, 250, 252, 0.8);
  font-weight: 700;
  font-size: 12px;
}

.badge-rank-3 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.15), rgba(148, 163, 184, 0.06));
  color: rgba(248, 250, 252, 0.6);
  font-weight: 600;
  font-size: 12px;
}

.badge-rank-normal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: rgba(248, 250, 252, 0.04);
  color: rgba(248, 250, 252, 0.4);
  font-weight: 500;
  font-size: 12px;
}
</style>
