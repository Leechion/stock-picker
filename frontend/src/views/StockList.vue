<template>
  <div class="stock-list-view">
    <div class="page-header">
      <h2 class="page-title">
        全部股票
        <span class="count-badge">{{ filteredStocks.length }}</span>
      </h2>
    </div>

    <div class="filter-bar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索股票代码或名称"
        :prefix-icon="Search"
        clearable
        style="width: 260px"
        @input="handleSearch"
      />
      <el-select
        v-model="industryFilter"
        placeholder="全部行业"
        clearable
        style="width: 160px"
        @change="handleSearch"
      >
        <el-option v-for="ind in industryList" :key="ind" :label="ind" :value="ind" />
      </el-select>
      <el-button text type="primary" @click="resetFilters" v-if="searchQuery || industryFilter">
        重置
      </el-button>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table
        :data="paginatedStocks"
        :loading="loading"
        stripe
        v-loading="loading"
        style="width: 100%"
        empty-text="暂无数据"
        @row-click="goToDetail"
        row-class-name="clickable-row"
      >
        <el-table-column prop="code" label="代码" width="120" align="center" sortable>
          <template #default="{ row }">
            <span class="code-text">{{ row.code }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="名称" min-width="140" sortable />

        <el-table-column prop="industry" label="行业" width="160" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.industry" size="small" effect="plain" :type="getIndustryTagType(row.industry)" round>
              {{ row.industry }}
            </el-tag>
            <span v-else class="text-dim">--</span>
          </template>
        </el-table-column>

        <el-table-column label="市场" width="100" align="center">
          <template #default="{ row }">
            <span class="market-tag" :class="row.code?.startsWith('6') ? 'sh' : 'sz'">
              {{ row.code?.startsWith('6') ? '沪' : '深' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="" width="48" align="center">
          <template #default>
            <el-icon class="row-arrow" :size="14" style="opacity: 0"><ArrowRight /></el-icon>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="filteredStocks.length"
          layout="total, sizes, prev, pager, next"
          background
          small
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search, ArrowRight } from '@element-plus/icons-vue'
import { useStocksStore } from '@/store'
import { getStocks } from '@/api/stocks'

const store = useStocksStore()
const router = useRouter()

const loading = ref(true)
const searchQuery = ref('')
const industryFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const filteredStocks = computed(() => {
  let list = store.stocks
  if (industryFilter.value) list = list.filter((s) => s.industry === industryFilter.value)
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter((s) => s.code.toLowerCase().includes(q) || (s.name || '').includes(q))
  }
  return list
})

const industryList = computed(() => {
  const set = new Set<string>()
  store.stocks.forEach((s) => { if (s.industry) set.add(s.industry) })
  return Array.from(set).sort()
})

const paginatedStocks = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredStocks.value.slice(start, start + pageSize.value)
})

function goToDetail(row: { code: string }) { router.push(`/stocks/${row.code}`) }
function handleSearch() { currentPage.value = 1 }
function resetFilters() { searchQuery.value = ''; industryFilter.value = ''; currentPage.value = 1 }

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

async function loadStocks() {
  loading.value = true
  try {
    const { data } = await getStocks()
    if (Array.isArray(data)) store.setStockList(data)
  } catch { /* handled */ }
  finally { loading.value = false }
}

onMounted(() => { loadStocks() })
</script>

<style scoped>
.stock-list-view {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: rgba(248, 250, 252, 0.9);
  letter-spacing: -0.02em;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.06);
  color: rgba(248, 250, 252, 0.5);
  font-size: 12px;
  font-weight: 500;
  font-family: 'Fira Code', monospace;
}

.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.table-card { border-radius: 10px; }

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 14px 0 0;
}

.code-text {
  font-family: 'Fira Code', monospace;
  font-weight: 500;
  font-size: 13px;
}

.text-dim { color: rgba(248, 250, 252, 0.2); }

.market-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.market-tag.sh {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.market-tag.sz {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.row-arrow {
  transition: opacity 0.15s;
}

:deep(.clickable-row) { cursor: pointer; }
:deep(.clickable-row:hover .row-arrow) { opacity: 1 !important; }
</style>
