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

      <el-table-column label="综合评分" width="130" align="center" sortable :sort-method="(a: RankingItem, b: RankingItem) => (a.score ?? 0) - (b.score ?? 0)">
        <template #default="{ row }">
          <div class="score-cell">
            <span class="score-value" :style="{ color: getScoreColor(row.score) }">
              {{ row.score?.toFixed?.(1) ?? '--' }}
            </span>
            <el-progress
              :percentage="Math.min(100, row.score ?? 0)"
              :color="getScoreColor(row.score)"
              :stroke-width="4"
              :show-text="false"
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
import { getScoreColor, getRankBadgeClass } from '@/utils/format'
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
</script>

<style scoped>
.stock-table-wrapper { width: 100%; }

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 14px 0 0;
}

.score-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.score-value {
  font-size: 14px;
  font-weight: 600;
  font-family: 'Fira Code', monospace;
}

.mini-score {
  font-size: 13px;
  font-weight: 600;
  font-family: 'Fira Code', monospace;
}

.code-text {
  font-family: 'Fira Code', monospace;
  font-weight: 500;
  font-size: 13px;
}

.text-dim { color: rgba(248, 250, 252, 0.2); }

:deep(.row-top3) {
  background-color: rgba(124, 58, 237, 0.04) !important;
}

:deep(.el-table__row) {
  cursor: pointer;
  transition: background 0.15s;
}

:deep(.el-table__row:hover td) {
  background-color: rgba(124, 58, 237, 0.05) !important;
}

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
