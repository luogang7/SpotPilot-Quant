<script setup lang="ts">
import {
  Activity,
  BarChart3,
  BrainCircuit,
  CandlestickChart,
  ClipboardList,
  Gauge,
  Languages,
  LayoutDashboard,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldAlert,
  Sun,
  Wallet,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'

import { useSystemStore } from '../app/store'
import { formatExchange, formatProvider, formatStatus } from '../shared/api/format'
import StatusBadge from '../shared/components/StatusBadge.vue'
import { useLanguage } from '../shared/i18n'
import type { AiProxyStatus, ExchangeStatus } from '../shared/types/workbench'

type ThemeMode = 'dark' | 'light'

const themeStorageKey = 'spotpilot-quant-theme'
const systemStore = useSystemStore()
const { language, setLanguage } = useLanguage()
const isSidebarCollapsed = ref(false)
const themeMode = ref<ThemeMode>(readInitialThemeMode())

const navItems = [
  { path: '/', label: '总览', desc: '系统状态', icon: LayoutDashboard },
  { path: '/market', label: '行情', desc: 'K 线与数据质量', icon: CandlestickChart },
  { path: '/strategy', label: '策略', desc: '参数与信号', icon: Gauge },
  { path: '/backtest', label: '回测', desc: '收益与明细', icon: BarChart3 },
  { path: '/ai-analysis', label: 'AI分析', desc: '评分与过滤', icon: BrainCircuit },
  { path: '/trading', label: '交易', desc: '现货执行', icon: Wallet },
  { path: '/risk', label: '风控', desc: '限制与熔断', icon: ShieldAlert },
  { path: '/logs', label: '日志', desc: '审计追踪', icon: ClipboardList },
  { path: '/settings', label: '设置', desc: '连接配置', icon: Settings },
]

const layoutClass = computed(() => ({
  'sidebar-collapsed': isSidebarCollapsed.value,
}))

applyThemeMode(themeMode.value)

onMounted(() => {
  systemStore.refresh().catch(() => undefined)
})

function readInitialThemeMode(): ThemeMode {
  const storedTheme = window.localStorage.getItem(themeStorageKey)
  return storedTheme === 'dark' ? 'dark' : 'light'
}

function applyThemeMode(mode: ThemeMode) {
  document.documentElement.dataset.theme = mode
  window.localStorage.setItem(themeStorageKey, mode)
}

function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
  applyThemeMode(mode)
}

function handleLanguageChange(event: Event) {
  const nextLanguage = (event.target as HTMLSelectElement).value
  if (nextLanguage === 'en' || nextLanguage === 'zh') {
    setLanguage(nextLanguage)
  }
}

function handleThemeModeChange(event: Event) {
  const nextThemeMode = (event.target as HTMLSelectElement).value
  if (nextThemeMode === 'dark' || nextThemeMode === 'light') {
    setThemeMode(nextThemeMode)
  }
}

function exchangeStatusLabel(exchange: ExchangeStatus) {
  const name = formatExchange(exchange.exchange)
  if (typeof exchange.latency_ms === 'number' && Number.isFinite(exchange.latency_ms)) {
    return `${name} ${exchange.latency_ms} 毫秒`
  }
  return `${name} ${formatStatus(exchange.state)}`
}

function aiProxyLabel(aiProxy: AiProxyStatus) {
  const label = `${formatProvider(aiProxy.provider)} / ${aiProxy.model}`
  return aiProxy.state === 'healthy' ? label : `${label} 待验证`
}

function dataLatencyLabel() {
  const latency = systemStore.dataLatency
  if (typeof latency !== 'number' || !Number.isFinite(latency)) {
    return '行情未验证'
  }
  return latency <= 0 ? '行情刚刚更新' : `行情更新 ${latency} 秒前`
}

function dataLatencyTone() {
  return typeof systemStore.dataLatency === 'number' && Number.isFinite(systemStore.dataLatency)
    ? 'success'
    : 'warning'
}
</script>

<template>
  <div class="app-shell" :class="layoutClass">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><Activity :size="18" /></div>
        <div class="brand-copy">
          <strong>SpotPilot Quant</strong>
          <span>现货量化领航台</span>
        </div>
        <button
          type="button"
          class="sidebar-toggle"
          :aria-label="isSidebarCollapsed ? '展开菜单' : '收起菜单'"
          :title="isSidebarCollapsed ? '展开菜单' : '收起菜单'"
          @click="isSidebarCollapsed = !isSidebarCollapsed"
        >
          <component :is="isSidebarCollapsed ? PanelLeftOpen : PanelLeftClose" :size="17" />
        </button>
      </div>

      <nav class="nav-list" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          exact-active-class="active"
          :title="isSidebarCollapsed ? `${item.label} - ${item.desc}` : undefined"
        >
          <span class="nav-icon"><component :is="item.icon" :size="17" /></span>
          <span class="nav-copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.desc }}</small>
          </span>
        </RouterLink>
      </nav>
    </aside>

    <div class="workbench">
      <header class="topbar">
        <div class="topbar-status">
          <StatusBadge
            v-for="exchange in systemStore.exchanges"
            :key="exchange.exchange"
            :label="exchangeStatusLabel(exchange)"
            :tone="exchange.state"
          />
          <StatusBadge
            v-if="systemStore.aiProxy"
            :label="aiProxyLabel(systemStore.aiProxy)"
            :tone="systemStore.aiProxy.state"
          />
          <StatusBadge :label="dataLatencyLabel()" :tone="dataLatencyTone()" />
        </div>

        <div class="topbar-actions">
          <div class="topbar-select-control language-select-control">
            <Languages :size="15" aria-hidden="true" />
            <select :value="language" aria-label="语言切换" title="语言切换" @change="handleLanguageChange">
              <option value="en">EN</option>
              <option value="zh">中文</option>
            </select>
          </div>

          <div class="topbar-select-control theme-select-control">
            <component :is="themeMode === 'dark' ? Moon : Sun" :size="15" aria-hidden="true" />
            <select :value="themeMode" aria-label="主题切换" title="主题切换" @change="handleThemeModeChange">
              <option value="dark">深色</option>
              <option value="light">浅色</option>
            </select>
          </div>
        </div>
      </header>

      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>
