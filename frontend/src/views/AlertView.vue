<template>
  <div class="alert-view">
    <div class="page-header">
      <div class="page-title-group">
        <h2 class="page-title">智能预警</h2>
        <span class="page-subtitle">自定义预警规则 · 自动检查通知</span>
      </div>
      <el-button type="primary" size="small" @click="showDialog()">添加规则</el-button>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table :data="rules" size="small" stripe v-loading="loading">
        <el-table-column prop="name" label="规则名称" width="150" />
        <el-table-column prop="rule_type" label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeLabel(row.rule_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="参数" min-width="180">
          <template #default="{ row }">
            <span class="font-mono" style="font-size: 11px">{{ formatParams(row.rule_type, row.params) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用" width="70" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" @change="toggleRule(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="showDialog(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="handleDelete(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && rules.length === 0" description="暂无预警规则" :image-size="80" />
    </el-card>

    <!-- Recent logs -->
    <el-card shadow="never" class="table-card" v-if="logs.length > 0">
      <template #header><span class="panel-title">最近触发</span></template>
      <div class="log-row" v-for="log in logs" :key="log.id">
        <span class="log-time">{{ log.created_at?.substring(5, 16) }}</span>
        <span class="log-rule">{{ log.rule_name }}</span>
        <span class="log-stock">{{ log.name }}({{ log.code }})</span>
        <span class="log-msg">{{ log.message }}</span>
      </div>
    </el-card>

    <!-- Dialog -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑规则' : '添加规则'" width="420px">
      <el-form label-position="top" size="small">
        <el-form-item label="规则名称">
          <el-input v-model="form.name" placeholder="如: 排名大幅上升" />
        </el-form-item>
        <el-form-item label="规则类型">
          <el-select v-model="form.rule_type" style="width: 100%">
            <el-option label="排名变动" value="rank_change" />
            <el-option label="评分阈值" value="score_threshold" />
            <el-option label="因子异常" value="factor_anomaly" />
          </el-select>
        </el-form-item>
        <template v-if="form.rule_type === 'rank_change'">
          <el-form-item label="方向">
            <el-select v-model="form.direction" style="width: 100%">
              <el-option label="上升" value="up" />
              <el-option label="下降" value="down" />
            </el-select>
          </el-form-item>
          <el-form-item label="变动位数">
            <el-input-number v-model="form.threshold" :min="1" :max="100" />
          </el-form-item>
        </template>
        <template v-if="form.rule_type === 'score_threshold'">
          <el-form-item label="方向">
            <el-select v-model="form.direction" style="width: 100%">
              <el-option label="超过" value="above" />
              <el-option label="低于" value="below" />
            </el-select>
          </el-form-item>
          <el-form-item label="评分阈值">
            <el-input-number v-model="form.threshold" :min="0" :max="100" />
          </el-form-item>
        </template>
        <template v-if="form.rule_type === 'factor_anomaly'">
          <el-form-item label="因子">
            <el-select v-model="form.factor_name" style="width: 100%">
              <el-option label="RSI" value="rsi" />
              <el-option label="MACD" value="macd" />
              <el-option label="资金流" value="capital_flow_score" />
              <el-option label="换手率" value="turnover_score" />
            </el-select>
          </el-form-item>
          <el-form-item label="条件">
            <el-select v-model="form.operator" style="width: 100%">
              <el-option label="大于" value=">" />
              <el-option label="小于" value="<" />
            </el-select>
          </el-form-item>
          <el-form-item label="阈值">
            <el-input-number v-model="form.value" :min="-1" :max="1" :step="0.1" :precision="2" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAlertRules, createAlertRule, updateAlertRule, deleteAlertRule, getAlertLogs } from '@/api/alerts'
import type { AlertRule, AlertLog } from '@/api/alerts'

const rules = ref<AlertRule[]>([])
const logs = ref<AlertLog[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref<AlertRule | null>(null)
const form = ref({ name: '', rule_type: 'rank_change', direction: 'up', threshold: 10, factor_name: 'rsi', operator: '>', value: 0.8, notify_wechat: true })

function typeLabel(t: string) {
  return { rank_change: '排名变动', score_threshold: '评分阈值', factor_anomaly: '因子异常' }[t] || t
}

function formatParams(type: string, p: Record<string, unknown>) {
  if (type === 'rank_change') return `${p.direction === 'up' ? '上升' : '下降'} ≥${p.threshold}位`
  if (type === 'score_threshold') return `${p.direction === 'above' ? '≥' : '≤'} ${p.threshold}分`
  if (type === 'factor_anomaly') return `${p.factor_name} ${p.operator} ${p.value}`
  return JSON.stringify(p)
}

async function load() {
  loading.value = true
  try {
    const [r, l] = await Promise.all([getAlertRules(), getAlertLogs(1, 10)])
    rules.value = r.data || []
    logs.value = l.data?.items || []
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function showDialog(rule?: AlertRule) {
  editing.value = rule || null
  if (rule) {
    form.value = { name: rule.name, rule_type: rule.rule_type, direction: String(rule.params.direction || 'up'), threshold: Number(rule.params.threshold || 10), factor_name: String(rule.params.factor_name || 'rsi'), operator: String(rule.params.operator || '>'), value: Number(rule.params.value ?? 0.8), notify_wechat: rule.notify_wechat }
  } else {
    form.value = { name: '', rule_type: 'rank_change', direction: 'up', threshold: 10, factor_name: 'rsi', operator: '>', value: 0.8, notify_wechat: true }
  }
  dialogVisible.value = true
}

function buildParams() {
  const f = form.value
  if (f.rule_type === 'rank_change') return JSON.stringify({ direction: f.direction, threshold: f.threshold })
  if (f.rule_type === 'score_threshold') return JSON.stringify({ direction: f.direction, threshold: f.threshold })
  return JSON.stringify({ factor_name: f.factor_name, operator: f.operator, value: f.value })
}

async function handleSave() {
  if (!form.value.name.trim()) { ElMessage.warning('请输入名称'); return }
  saving.value = true
  try {
    const params = buildParams()
    if (editing.value) {
      await updateAlertRule(editing.value.id, { name: form.value.name, params })
    } else {
      await createAlertRule({ name: form.value.name, rule_type: form.value.rule_type, params })
    }
    ElMessage.success(editing.value ? '已更新' : '已创建')
    dialogVisible.value = false
    await load()
  } catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

async function toggleRule(rule: AlertRule) {
  try { await updateAlertRule(rule.id, { enabled: rule.enabled }) }
  catch { rule.enabled = !rule.enabled }
}

async function handleDelete(id: number) {
  try { await deleteAlertRule(id); ElMessage.success('已删除'); await load() }
  catch { ElMessage.error('删除失败') }
}

onMounted(load)
</script>

<style scoped>
.alert-view { max-width: 1000px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title-group { display: flex; align-items: baseline; gap: 12px; }
.page-title { margin: 0; font-size: 22px; font-weight: 700; color: var(--text-primary); }
.page-subtitle { font-size: 12px; color: var(--text-muted); }
.font-mono { font-family: 'Fira Code', monospace; }
.table-card { margin-bottom: 12px; border-radius: 10px; }
.panel-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.log-row { display: flex; gap: 8px; padding: 5px 0; font-size: 12px; border-bottom: 1px solid var(--border-subtle); }
.log-time { color: var(--text-muted); width: 65px; flex-shrink: 0; font-family: 'Fira Code', monospace; font-size: 11px; }
.log-rule { color: var(--text-secondary); width: 80px; flex-shrink: 0; }
.log-stock { font-weight: 500; width: 90px; flex-shrink: 0; }
.log-msg { color: var(--text-secondary); flex: 1; }
</style>
