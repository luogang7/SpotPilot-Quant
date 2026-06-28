import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('../features/dashboard/DashboardView.vue') },
    { path: '/market', name: 'market', component: () => import('../features/market/MarketView.vue') },
    { path: '/strategy', name: 'strategy', component: () => import('../features/strategy/StrategyView.vue') },
    { path: '/backtest', name: 'backtest', component: () => import('../features/backtest/BacktestView.vue') },
    { path: '/ai-analysis', name: 'ai-analysis', component: () => import('../features/ai-analysis/AiAnalysisView.vue') },
    { path: '/trading', name: 'trading', component: () => import('../features/trading/TradingView.vue') },
    { path: '/risk', name: 'risk', component: () => import('../features/risk/RiskView.vue') },
    { path: '/logs', name: 'logs', component: () => import('../features/logs/LogsView.vue') },
    { path: '/settings', name: 'settings', component: () => import('../features/settings/SettingsView.vue') },
  ],
})

