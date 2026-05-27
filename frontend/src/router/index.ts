import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'StockRanking',
    component: () => import('@/views/StockRanking.vue'),
    meta: { title: '股票排行' },
  },
  {
    path: '/sectors',
    name: 'SectorRanking',
    component: () => import('@/views/SectorRanking.vue'),
    meta: { title: '板块排行' },
  },
  {
    path: '/stocks',
    name: 'StockList',
    component: () => import('@/views/StockList.vue'),
    meta: { title: '股票列表' },
  },
  {
    path: '/stocks/:code',
    name: 'StockDetail',
    component: () => import('@/views/StockDetail.vue'),
    meta: { title: '股票详情' },
  },
  {
    path: '/analysis',
    name: 'FactorAnalysis',
    component: () => import('@/views/FactorAnalysis.vue'),
    meta: { title: '因子分析' },
  },
  {
    path: '/trading',
    name: 'Trading',
    component: () => import('@/views/TradingView.vue'),
    meta: { title: '模拟交易' },
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/BacktestView.vue'),
    meta: { title: '策略回测' },
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('@/views/AlertView.vue'),
    meta: { title: '智能预警' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: '系统设置' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to, _from, next) => {
  document.title = `${to.meta.title || '智能选股'} - A股量化多因子分析`
  next()
})

export default router