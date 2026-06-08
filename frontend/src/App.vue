<template>
  <el-config-provider :locale="locale">
    <div id="app-layout">
      <div class="bg-mesh"></div>

      <el-container class="app-container">
        <el-header class="app-header">
          <div class="header-content">
            <div class="header-left">
              <div class="logo-icon">
                <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
                  <line x1="6" y1="24" x2="6" y2="17" stroke="white" stroke-width="1.4" stroke-linecap="round" opacity="0.6"/>
                  <rect x="3.5" y="20" width="5" height="4" rx="1" fill="none" stroke="white" stroke-width="1.2" opacity="0.6"/>
                  <line x1="13" y1="24" x2="13" y2="14" stroke="#ef4444" stroke-width="1.4" stroke-linecap="round"/>
                  <rect x="10.5" y="17" width="5" height="7" rx="1" fill="#ef4444" stroke="#ef4444" stroke-width="0.8"/>
                  <line x1="20" y1="22" x2="20" y2="12" stroke="#ef4444" stroke-width="1.4" stroke-linecap="round"/>
                  <rect x="17.5" y="15" width="5" height="7" rx="1" fill="#ef4444" stroke="#ef4444" stroke-width="0.8"/>
                  <g class="candle-rocket">
                    <g class="candle-normal">
                      <line x1="27" y1="20" x2="27" y2="10" stroke="#ef4444" stroke-width="1.6" stroke-linecap="round"/>
                      <rect x="24.5" y="13" width="5" height="7" rx="1" fill="#ef4444" stroke="#ef4444" stroke-width="0.8"/>
                    </g>
                    <g class="candle-limitup">
                      <line x1="27" y1="20" x2="27" y2="4" stroke="#ef4444" stroke-width="1.6" stroke-linecap="round"/>
                      <rect x="24.5" y="6" width="5" height="14" rx="1" fill="#ef4444" stroke="#ef4444" stroke-width="0.8"/>
                    </g>
                  </g>
                </svg>
              </div>
              <div class="header-titles">
                <span class="app-title">QuantBlade</span>
                <span class="app-subtitle">A股量化多因子选股</span>
                <span class="status-dot">
                  <span class="status-pulse"></span>
                  <span class="status-text">Live</span>
                </span>
              </div>
            </div>
            <div class="header-right">
              <el-button
                :icon="darkMode ? 'Moon' : 'Sunny'"
                circle
                size="small"
                class="theme-toggle"
                @click="darkMode = !darkMode"
              />
            </div>
          </div>
        </el-header>

        <el-container class="body-wrap">
          <el-aside :width="isCollapse ? '60px' : '200px'" class="app-aside">
            <div class="collapse-btn" @click="isCollapse = !isCollapse">
              <el-icon :size="16"><Fold v-if="!isCollapse" /><Expand v-else /></el-icon>
            </div>
            <el-menu
              :default-active="activeRoute"
              :collapse="isCollapse"
              :collapse-transition="false"
              router
              class="app-menu"
            >
              <el-menu-item index="/">
                <el-icon><DataAnalysis /></el-icon>
                <template #title>股票排行</template>
              </el-menu-item>
              <el-menu-item index="/sectors">
                <el-icon><PieChart /></el-icon>
                <template #title>板块排行</template>
              </el-menu-item>
              <el-menu-item index="/stocks">
                <el-icon><ListIcon /></el-icon>
                <template #title>股票列表</template>
              </el-menu-item>
              <el-menu-item index="/analysis">
                <el-icon><Odometer /></el-icon>
                <template #title>因子分析</template>
              </el-menu-item>
              <el-menu-item index="/trading">
                <el-icon><TrendCharts /></el-icon>
                <template #title>模拟交易</template>
              </el-menu-item>
              <el-menu-item index="/backtest">
                <el-icon><DataLine /></el-icon>
                <template #title>策略回测</template>
              </el-menu-item>
              <el-menu-item index="/alerts">
                <el-icon><Bell /></el-icon>
                <template #title>智能预警</template>
              </el-menu-item>
              <el-menu-item index="/ai-recommend">
                <el-icon><MagicStick /></el-icon>
                <template #title>AI明日推荐</template>
              </el-menu-item>
              <el-menu-item index="/settings">
                <el-icon><Setting /></el-icon>
                <template #title>系统设置</template>
              </el-menu-item>
            </el-menu>
            <div class="sidebar-footer" v-if="!isCollapse">
              <span class="version-tag">v0.1.0</span>
            </div>
          </el-aside>

          <el-main class="app-main">
            <router-view v-slot="{ Component }">
              <transition name="fade" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
          </el-main>
        </el-container>
      </el-container>
    </div>
  </el-config-provider>
</template>

<script lang="ts" setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Fold,
  Expand,
  DataAnalysis,
  PieChart,
  List as ListIcon,
  Odometer,
  Setting,
  TrendCharts,
  DataLine,
  Bell,
  MagicStick,
} from '@element-plus/icons-vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

const route = useRoute()
const activeRoute = computed(() => route.path)
const isCollapse = ref(false)
const darkMode = ref(true)

const locale = zhCn

watch(darkMode, (val) => {
  if (val) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}, { immediate: true })
</script>

<style scoped>
#app-layout {
  height: 100vh;
  position: relative;
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

.bg-mesh {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  background: var(--bg-mesh);
  pointer-events: none;
  z-index: 0;
}

.app-container {
  position: relative;
  z-index: 1;
  height: 100vh;
}

/* Header */
.app-header {
  background: var(--header-bg);
  backdrop-filter: blur(16px) saturate(1.3);
  -webkit-backdrop-filter: blur(16px) saturate(1.3);
  border-bottom: 1px solid var(--border-subtle);
  padding: 0 24px;
  height: 52px !important;
  display: flex;
  align-items: center;
  z-index: 10;
  flex-shrink: 0;
  position: relative;
}

.app-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(124, 58, 237, 0.2), rgba(99, 102, 241, 0.15), transparent);
}

.body-wrap {
  overflow: hidden;
}

.header-content {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 10px rgba(124, 58, 237, 0.3);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.logo-icon:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.4);
}

/* Candle rocket — last candle hits limit-up on hover */
.candle-rocket {
  position: relative;
}
.candle-normal {
  transition: opacity 0.3s ease;
}
.candle-limitup {
  opacity: 0;
  transition: opacity 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.logo-icon:hover .candle-normal {
  opacity: 0;
}
.logo-icon:hover .candle-limitup {
  opacity: 1;
}

.header-titles {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.app-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  font-family: 'Inter', -apple-system, 'PingFang SC', sans-serif;
}

.app-subtitle {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  padding-left: 10px;
  border-left: 1px solid var(--border-subtle);
  letter-spacing: 0.04em;
}

.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding-left: 10px;
  border-left: 1px solid var(--border-subtle);
}

.status-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
  animation: pulse 2s ease-in-out infinite;
}

.status-text {
  font-size: 10px;
  font-weight: 500;
  color: #22c55e;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.header-right {
  display: flex;
  align-items: center;
}

.theme-toggle {
  background: var(--btn-bg) !important;
  border: 1px solid var(--border-subtle) !important;
  color: var(--text-secondary) !important;
  transition: all 0.2s ease;
}

.theme-toggle:hover {
  background: var(--btn-hover-bg) !important;
  color: var(--text-primary) !important;
}

/* Sidebar */
.app-aside {
  background: var(--sidebar-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-right: 1px solid var(--border-subtle);
  transition: width 0.2s ease;
  overflow: hidden;
}

.collapse-btn {
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-subtle);
  transition: all 0.2s ease;
}

.collapse-btn:hover {
  color: var(--text-secondary);
  background: var(--hover-bg);
}

.app-menu {
  border-right: none !important;
  height: calc(100vh - 88px);
  padding-top: 6px;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: var(--text-secondary);
  --el-menu-active-color: #7c3aed;
  --el-menu-hover-bg-color: var(--hover-bg);
}

.app-menu .el-menu-item {
  margin: 1px 8px;
  border-radius: 8px;
  height: 38px;
  line-height: 38px;
  font-size: 13px;
  font-weight: 400;
  transition: all 0.2s ease;
}

.app-menu .el-menu-item:hover {
  background: var(--hover-bg) !important;
}

.app-menu .el-menu-item.is-active {
  background: var(--active-bg) !important;
  color: #7c3aed !important;
  font-weight: 500;
  box-shadow: inset 3px 0 0 #7c3aed;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
}

.version-tag {
  font-size: 10px;
  color: var(--text-muted);
  padding: 2px 8px;
  background: var(--btn-bg);
  border-radius: 4px;
  font-family: 'Fira Code', monospace;
}

/* Main */
.app-main {
  background: transparent;
  flex: 1;
  padding: 20px 24px;
  overflow-y: auto;
}

/* Transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease, transform 0.1s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.fade-leave-to {
  opacity: 0;
}
</style>

<style>
/* ===== CSS Variables — Light (default) ===== */
:root {
  --bg-body: #f8fafc;
  --bg-mesh: none;
  --bg-card: #fff;
  --bg-card-hover: #fff;
  --header-bg: rgba(255, 255, 255, 0.85);
  --sidebar-bg: rgba(248, 250, 252, 0.9);
  --text-primary: #1e293b;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --border-subtle: rgba(0, 0, 0, 0.06);
  --border-card: rgba(0, 0, 0, 0.08);
  --hover-bg: rgba(0, 0, 0, 0.03);
  --active-bg: rgba(124, 58, 237, 0.06);
  --btn-bg: rgba(0, 0, 0, 0.04);
  --btn-hover-bg: rgba(0, 0, 0, 0.06);
  --input-bg: #fff;
  --input-border: rgba(0, 0, 0, 0.12);
  --input-hover-border: rgba(124, 58, 237, 0.4);
  --input-focus-border: rgba(124, 58, 237, 0.6);
  --tag-bg: rgba(124, 58, 237, 0.06);
  --tag-border: rgba(124, 58, 237, 0.15);
  --tag-color: #7c3aed;
  --progress-bg: rgba(0, 0, 0, 0.06);
  --table-header-bg: rgba(0, 0, 0, 0.02);
  --table-hover-bg: rgba(124, 58, 237, 0.04);
  --table-border: rgba(0, 0, 0, 0.06);
  --table-text: #334155;
  --table-header-text: #94a3b8;
  --scrollbar-thumb: rgba(0, 0, 0, 0.1);
  --scrollbar-thumb-hover: rgba(0, 0, 0, 0.2);
  --card-shadow: 0 1px 4px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.03);
  --card-hover-shadow: 0 4px 12px rgba(0,0,0,0.06), 0 1px 4px rgba(0,0,0,0.04);
}

/* ===== CSS Variables — Dark ===== */
html.dark {
  color-scheme: dark;
  --bg-body: #020617;
  --bg-mesh:
    radial-gradient(ellipse 70% 50% at 15% 25%, rgba(99, 54, 198, 0.08) 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 80% 75%, rgba(59, 130, 246, 0.05) 0%, transparent 60%);
  --bg-card: rgba(248, 250, 252, 0.02);
  --bg-card-hover: rgba(248, 250, 252, 0.04);
  --header-bg: rgba(2, 6, 23, 0.7);
  --sidebar-bg: rgba(2, 6, 23, 0.5);
  --text-primary: rgba(248, 250, 252, 0.95);
  --text-secondary: rgba(248, 250, 252, 0.6);
  --text-muted: rgba(248, 250, 252, 0.3);
  --border-subtle: rgba(248, 250, 252, 0.04);
  --border-card: rgba(248, 250, 252, 0.05);
  --hover-bg: rgba(255, 255, 255, 0.03);
  --active-bg: rgba(124, 58, 237, 0.1);
  --btn-bg: rgba(255, 255, 255, 0.04);
  --btn-hover-bg: rgba(255, 255, 255, 0.08);
  --input-bg: rgba(248, 250, 252, 0.03);
  --input-border: rgba(248, 250, 252, 0.06);
  --input-hover-border: rgba(124, 58, 237, 0.2);
  --input-focus-border: rgba(124, 58, 237, 0.4);
  --tag-bg: rgba(124, 58, 237, 0.08);
  --tag-border: rgba(124, 58, 237, 0.15);
  --tag-color: #a78bfa;
  --progress-bg: rgba(248, 250, 252, 0.05);
  --table-header-bg: rgba(248, 250, 252, 0.015);
  --table-hover-bg: rgba(124, 58, 237, 0.05);
  --table-border: rgba(248, 250, 252, 0.04);
  --table-text: rgba(248, 250, 252, 0.75);
  --table-header-text: rgba(248, 250, 252, 0.4);
  --scrollbar-thumb: rgba(248, 250, 252, 0.08);
  --scrollbar-thumb-hover: rgba(248, 250, 252, 0.15);
  --card-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  --card-hover-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

/* ===== Base ===== */
body {
  background-color: var(--bg-body);
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-weight: 400;
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
  margin: 0;
  transition: background-color 0.3s ease, color 0.3s ease;
}

h1, h2, h3, h4, h5, h6 {
  font-family: 'Inter', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

h2 { font-size: 20px; font-weight: 700; }
h3 { font-size: 16px; font-weight: 600; }

/* ===== Card ===== */
.el-card {
  background: var(--bg-card) !important;
  border: 1px solid var(--border-card) !important;
  border-radius: 12px !important;
  box-shadow: var(--card-shadow) !important;
  transition: all 0.25s ease;
}

.el-card:hover {
  background: var(--bg-card-hover) !important;
  box-shadow: var(--card-hover-shadow) !important;
}

html.dark .el-card:hover {
  border-color: rgba(124, 58, 237, 0.15) !important;
}

.el-card__header {
  border-bottom-color: var(--border-subtle) !important;
  padding: 14px 20px !important;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.el-card__body {
  padding: 18px 20px !important;
}

/* ===== Table ===== */
.el-table {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--table-header-bg);
  --el-table-row-hover-bg-color: var(--table-hover-bg);
  --el-table-border-color: var(--table-border);
  --el-table-text-color: var(--table-text);
  --el-table-header-text-color: var(--table-header-text);
  --el-table-row-height: 48px;
  font-family: 'Inter', sans-serif;
}

.el-table th.el-table__cell {
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.01em;
  text-transform: none;
}

.el-table td.el-table__cell {
  font-size: 13px;
}

/* ===== Button ===== */
.el-button--primary {
  background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
  border: none !important;
  font-weight: 500;
  letter-spacing: -0.01em;
}

.el-button--primary:hover {
  box-shadow: 0 0 20px rgba(124, 58, 237, 0.3);
  transform: translateY(-1px);
}

.el-button {
  font-family: 'Inter', sans-serif;
  font-weight: 500;
  border-radius: 8px;
  transition: all 0.2s ease;
}

/* ===== Tags ===== */
.el-tag {
  background: var(--tag-bg) !important;
  border-color: var(--tag-border) !important;
  color: var(--tag-color) !important;
  font-weight: 500;
  font-size: 12px;
}

/* ===== Progress ===== */
.el-progress-bar__outer {
  background: var(--progress-bg) !important;
  border-radius: 6px !important;
}

.el-progress-bar__inner {
  border-radius: 6px !important;
  transition: width 0.6s ease;
}

/* ===== Input ===== */
.el-input__wrapper,
.el-select .el-input__wrapper {
  background: var(--input-bg) !important;
  box-shadow: 0 0 0 1px var(--input-border) inset !important;
  border-radius: 8px !important;
  font-family: 'Inter', sans-serif;
  transition: all 0.2s ease;
}

.el-input__wrapper:hover,
.el-select:hover .el-input__wrapper {
  box-shadow: 0 0 0 1px var(--input-hover-border) inset !important;
}

.el-input__wrapper.is-focus,
.el-select .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px var(--input-focus-border) inset !important;
}

/* ===== Menu ===== */
.el-menu {
  --el-menu-bg-color: transparent !important;
}

/* ===== Empty State ===== */
.el-empty__description p {
  color: var(--text-muted) !important;
  font-size: 13px;
}

.el-empty__image svg {
  fill: var(--text-muted);
  opacity: 0.3;
}

/* ===== Descriptions ===== */
.el-descriptions__body {
  background: transparent !important;
}

.el-descriptions__label {
  color: var(--text-muted) !important;
  font-weight: 500;
}

.el-descriptions__content {
  color: var(--text-primary) !important;
}

/* ===== Pagination ===== */
.el-pagination {
  --el-pagination-bg-color: transparent;
  --el-pagination-text-color: var(--text-secondary);
  --el-pagination-button-bg-color: var(--btn-bg);
  --el-pagination-hover-color: #7c3aed;
  --el-pagination-button-active-bg: rgba(124, 58, 237, 0.15);
  font-family: 'Inter', sans-serif;
}

.el-pagination .is-active {
  background: rgba(124, 58, 237, 0.15) !important;
  color: #a78bfa !important;
  font-weight: 600;
}

/* ===== Dialog ===== */
.el-dialog {
  background: var(--bg-card) !important;
  border: 1px solid var(--border-card) !important;
}

.el-dialog__title {
  color: var(--text-primary) !important;
}

.el-dialog__header {
  border-bottom-color: var(--border-subtle) !important;
}

/* ===== Drawer ===== */
.el-drawer {
  background: var(--bg-body) !important;
}

.el-drawer__header {
  color: var(--text-primary) !important;
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 6px;
  border: 2px solid transparent;
  background-clip: padding-box;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
  background-clip: padding-box;
}

/* ===== Selection ===== */
::selection {
  background: rgba(124, 58, 237, 0.3);
  color: #fff;
}

/* ===== Data Font Utility ===== */
.font-mono {
  font-family: 'Fira Code', 'SF Mono', 'Cascadia Code', 'Roboto Mono', monospace;
  font-feature-settings: 'tnum' 1, 'cv01' 1;
  letter-spacing: 0.01em;
}

/* Fira Code tabular numbers + alternate 'a' for cleaner look */
.font-mono--tight {
  font-family: 'Fira Code', 'SF Mono', monospace;
  font-feature-settings: 'tnum' 1, 'calt' 0;
  letter-spacing: 0;
}

/* ===== Stock Colors (theme-aware) ===== */
.text-up {
  color: #ef4444;
}
.text-down {
  color: #22c55e;
}
html.dark .text-up {
  color: #ef4444;
}
html.dark .text-down {
  color: #22c55e;
}
</style>
