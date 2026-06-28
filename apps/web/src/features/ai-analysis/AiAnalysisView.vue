<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  Activity,
  CheckCircle2,
  Clipboard,
  Database,
  FileJson,
  PanelRightOpen,
  RefreshCw,
  Search,
  X,
} from 'lucide-vue-next'

import { api } from '../../shared/api/client'
import {
  formatAction,
  formatBoolean,
  formatDateTime,
  formatMarketRegime,
  formatMessage,
  formatProvider,
  formatRiskLevel,
  formatStatus,
} from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MarketSymbolPicker from '../../shared/components/MarketSymbolPicker.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import { useMarketSymbols, type ExchangeId } from '../../shared/config/markets'
import type {
  AiAnalysis,
  AiDecisionSignal,
  AiDecisionSignalAction,
  AiDecisionSignalHorizon,
  AiDecisionSignalPlanQuality,
  AiDecisionSignalStatus,
} from '../../shared/types/workbench'

type AnalysisScope = 'market' | 'symbol'
type DetailTab = 'summary' | 'evidence' | 'quality' | 'metadata'
type SignalTone = 'success' | 'warning' | 'danger' | 'default'
type SignalFilter = 'all' | AiDecisionSignalAction

const analysisScope = ref<AnalysisScope>('market')
const newsSymbol = ref('BTC/USDT')
const newsExchange = ref<ExchangeId>('binance')
const forceNewsRefresh = ref(false)
const forceAiRefresh = ref(false)
const selectedSignal = ref<AiDecisionSignal | null>(null)
const detailTab = ref<DetailTab>('summary')
const signalActionFilter = ref<SignalFilter>('all')
const signalStatusFilter = ref<'all' | AiDecisionSignalStatus>('active')
const latestSymbolQuery = ref('')
const latestSignalResult = ref<AiDecisionSignal | null>(null)
const latestSignalLoading = ref(false)
const latestSignalError = ref('')
const validationInput = ref(
  JSON.stringify(
    {
      market_regime: 'trend',
      sentiment_score: 0,
      risk_level: 'low',
      event_risk: false,
      allowed_direction: 'long_only',
      confidence: 0.7,
    },
    null,
    2,
  ),
)
const validating = ref(false)
const refreshingNews = ref(false)
const validationError = ref('')
const validatedAnalysis = ref<AiAnalysis | null>(null)

const { isMarketSymbolSupported, firstMarketSymbolForExchange } = useMarketSymbols(newsExchange)
const targetSymbol = computed(() => (analysisScope.value === 'market' ? 'MARKET' : newsSymbol.value))
const targetLabel = computed(() => (analysisScope.value === 'market' ? '全市场' : newsSymbol.value))
const targetDetail = computed(() =>
  analysisScope.value === 'market'
    ? '聚合主流币种新闻、监管和系统性风险'
    : `${newsSymbol.value} 新闻情绪和现货过滤`,
)
const aiQuery = computed(() => ({
  scope: analysisScope.value,
  symbol: analysisScope.value === 'symbol' ? newsSymbol.value : undefined,
  exchange: newsExchange.value,
  refresh: forceAiRefresh.value || undefined,
  fast: forceAiRefresh.value ? undefined : true,
}))
const newsQuery = computed(() => ({
  symbol: targetSymbol.value,
  refresh: forceNewsRefresh.value || undefined,
}))

const { data, loading, error, refresh: refreshAiAnalysis } = useResource(() => api.getAiAnalysis(aiQuery.value))
const {
  data: newsData,
  loading: newsLoading,
  error: newsError,
  refresh: refreshNewsResource,
} = useResource(() => api.getNewsSentiment(newsQuery.value), false)

const analysisTargetMatchesSelection = computed(
  () => data.value?.analysis_scope === analysisScope.value && (data.value.symbol ?? targetSymbol.value) === targetSymbol.value,
)
const displayData = computed(() => (analysisTargetMatchesSelection.value ? data.value : null))
const hasStaleAnalysisTarget = computed(() => data.value !== null && !analysisTargetMatchesSelection.value)
const staleAnalysisMessage = computed(() => {
  const source = data.value?.symbol === 'MARKET' ? '全市场' : data.value?.symbol || '其他目标'
  return `当前缓存为 ${source}，尚未匹配 ${targetLabel.value}。请刷新生成当前目标的 AI 建议信号。`
})
const currentSignal = computed(() => displayData.value?.decision_signal ?? null)
const signalItems = computed(() => {
  const items = [currentSignal.value, latestSignalResult.value].filter((item): item is AiDecisionSignal => Boolean(item))
  const unique = new Map<string, AiDecisionSignal>()
  items.forEach((item) => unique.set(item.signal_id, item))
  return Array.from(unique.values())
})
const filteredSignals = computed(() =>
  signalItems.value.filter((item) => {
    const actionMatched = signalActionFilter.value === 'all' || item.action === signalActionFilter.value
    const statusMatched = signalStatusFilter.value === 'all' || item.status === signalStatusFilter.value
    return actionMatched && statusMatched
  }),
)
const signalStats = computed(() => {
  const source = signalItems.value
  const active = source.filter((item) => item.status === 'active')
  const confidenceValues = source
    .map((item) => item.confidence)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const avgConfidence = confidenceValues.length
    ? confidenceValues.reduce((total, value) => total + value, 0) / confidenceValues.length
    : null
  return {
    total: source.length,
    active: active.length,
    defensive: active.filter((item) => ['reduce', 'sell', 'avoid', 'alert'].includes(item.action)).length,
    bullish: active.filter((item) => ['buy', 'add'].includes(item.action)).length,
    avgConfidence,
  }
})
const selectedSignalDisplay = computed(() => {
  if (!selectedSignal.value) {
    return null
  }
  return signalItems.value.find((item) => item.signal_id === selectedSignal.value?.signal_id) ?? selectedSignal.value
})
const payload = computed(() => JSON.stringify(displayData.value?.structured_payload ?? {}, null, 2))
const rationaleStatus = computed(() => {
  if (displayData.value?.provider && displayData.value.provider !== 'local_ai_mock') {
    return { label: 'AI 返回结果', tone: 'success' as const }
  }
  return { label: '本地结构校验', tone: 'warning' as const }
})
const newsStatusTone = computed(() => {
  if (!newsData.value || newsData.value.status === 'disabled') {
    return 'warning' as const
  }
  if (newsData.value.status === 'ok' && !newsData.value.event_risk) {
    return 'success' as const
  }
  return 'warning' as const
})
const latestSearchPlaceholder = computed(() => (newsExchange.value === 'okx' ? '例如 BTC/USDT、OKB/USDT' : '例如 BTC/USDT、ETH/USDT'))

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '-'
  }
  return Number(value).toFixed(digits).replace(/\.?0+$/, '')
}

function formatConfidence(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '-'
  }
  const normalized = Math.abs(value) <= 1 ? value * 100 : value
  return `${formatNumber(normalized, 1)}%`
}

function formatJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2)
}

function formatEntryRange(signal: AiDecisionSignal) {
  const hasLow = typeof signal.entry_low === 'number'
  const hasHigh = typeof signal.entry_high === 'number'
  if (hasLow && hasHigh) {
    return signal.entry_low === signal.entry_high
      ? formatNumber(signal.entry_low)
      : `${formatNumber(signal.entry_low)} - ${formatNumber(signal.entry_high)}`
  }
  if (hasLow) {
    return formatNumber(signal.entry_low)
  }
  if (hasHigh) {
    return formatNumber(signal.entry_high)
  }
  return '-'
}

function actionLabel(action: AiDecisionSignalAction, fallback?: string | null) {
  const labels: Record<AiDecisionSignalAction, string> = {
    buy: '买入',
    add: '加仓',
    hold: '持有',
    reduce: '减仓',
    sell: '卖出',
    watch: '观察',
    avoid: '回避',
    alert: '警报',
  }
  return fallback || labels[action] || action
}

function actionTone(action: AiDecisionSignalAction): SignalTone {
  if (['buy', 'add', 'hold'].includes(action)) {
    return 'success'
  }
  if (['watch', 'alert'].includes(action)) {
    return 'warning'
  }
  if (['reduce', 'sell', 'avoid'].includes(action)) {
    return 'danger'
  }
  return 'default'
}

function statusLabel(status: AiDecisionSignalStatus) {
  const labels: Record<AiDecisionSignalStatus, string> = {
    active: '有效',
    expired: '已过期',
    invalidated: '已失效',
    closed: '已关闭',
    archived: '已归档',
  }
  return labels[status]
}

function statusTone(status: AiDecisionSignalStatus): SignalTone {
  if (status === 'active') {
    return 'success'
  }
  if (status === 'invalidated') {
    return 'danger'
  }
  if (status === 'expired') {
    return 'warning'
  }
  return 'default'
}

function horizonLabel(horizon: AiDecisionSignalHorizon | null | undefined) {
  if (!horizon) {
    return '-'
  }
  const labels: Record<AiDecisionSignalHorizon, string> = {
    intraday: '日内',
    '1d': '1 日',
    '3d': '3 日',
    '5d': '5 日',
    '10d': '10 日',
    swing: '波段',
    long: '长期',
  }
  return labels[horizon]
}

function planQualityLabel(value: AiDecisionSignalPlanQuality) {
  const labels: Record<AiDecisionSignalPlanQuality, string> = {
    complete: '完整',
    partial: '部分',
    minimal: '最低',
    unknown: '未知',
  }
  return labels[value]
}

function marketPhaseLabel(value: string | null | undefined) {
  if (value === 'crypto_24x7') {
    return '加密市场 24x7'
  }
  return value ? formatStatus(value) : '-'
}

function selectSignal(signal: AiDecisionSignal) {
  selectedSignal.value = signal
  detailTab.value = 'summary'
}

async function refreshAll() {
  forceAiRefresh.value = true
  try {
    await refreshAiAnalysis()
  } finally {
    forceAiRefresh.value = false
  }
}

async function refreshNews() {
  refreshingNews.value = true
  forceNewsRefresh.value = true
  forceAiRefresh.value = true
  try {
    await refreshNewsResource()
    await refreshAiAnalysis()
  } finally {
    forceNewsRefresh.value = false
    forceAiRefresh.value = false
    refreshingNews.value = false
  }
}

async function searchLatestSignal() {
  const symbol = latestSymbolQuery.value.trim()
  if (!symbol) {
    return
  }
  latestSignalLoading.value = true
  latestSignalError.value = ''
  latestSignalResult.value = null
  try {
    const result = await api.getAiAnalysis({
      scope: 'symbol',
      symbol,
      exchange: newsExchange.value,
      refresh: true,
    })
    latestSignalResult.value = result.decision_signal ?? null
    if (!result.decision_signal) {
      latestSignalError.value = '该标的暂未生成 AI 建议信号'
    }
  } catch (err) {
    latestSignalError.value = err instanceof Error ? err.message : '查询最新信号失败'
  } finally {
    latestSignalLoading.value = false
  }
}

async function validatePayload() {
  validating.value = true
  validationError.value = ''
  try {
    const parsed = JSON.parse(validationInput.value) as Record<string, unknown>
    validatedAnalysis.value = await api.validateAiPayload(parsed)
  } catch (err) {
    validationError.value = err instanceof Error ? err.message : '结构校验失败'
  } finally {
    validating.value = false
  }
}

watch(analysisScope, () => {
  latestSignalResult.value = null
  void refreshAiAnalysis()
})

watch(newsSymbol, () => {
  if (analysisScope.value === 'symbol') {
    latestSignalResult.value = null
    void refreshAiAnalysis()
  }
})

watch(newsExchange, (exchange) => {
  latestSignalResult.value = null
  if (!isMarketSymbolSupported(newsSymbol.value, exchange)) {
    newsSymbol.value = firstMarketSymbolForExchange(exchange)
  }
})

</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">AI分析</h1>
        <p class="page-subtitle">按市场、交易对和新闻上下文生成结构化评分和过滤条件，保留风险、数据质量和模型证据。</p>
      </div>
      <div class="page-actions">
        <button type="button" class="ghost-button" @click="refreshAll">
          <RefreshCw :size="15" />
          刷新
        </button>
      </div>
    </header>

    <SectionPanel title="筛选与目标" note="生成当前对象的最新 AI 建议信号">
      <div class="panel-body ai-signal-filters">
        <div class="mode-switch">
          <button type="button" :class="{ active: analysisScope === 'market' }" @click="analysisScope = 'market'">
            大盘
          </button>
          <button type="button" :class="{ active: analysisScope === 'symbol' }" @click="analysisScope = 'symbol'">
            单币种
          </button>
        </div>
        <MarketSymbolPicker
          v-model="newsSymbol"
          :exchange="newsExchange"
          :disabled="analysisScope === 'market'"
          :class="{ 'is-disabled': analysisScope === 'market' }"
        />
        <select v-model="newsExchange" :disabled="analysisScope === 'market'">
          <option value="binance">币安</option>
          <option value="okx">OKX</option>
        </select>
        <select v-model="signalActionFilter">
          <option value="all">全部动作</option>
          <option value="buy">买入</option>
          <option value="add">加仓</option>
          <option value="hold">持有</option>
          <option value="reduce">减仓</option>
          <option value="sell">卖出</option>
          <option value="watch">观察</option>
          <option value="avoid">回避</option>
          <option value="alert">警报</option>
        </select>
        <select v-model="signalStatusFilter">
          <option value="all">全部状态</option>
          <option value="active">有效</option>
          <option value="expired">已过期</option>
          <option value="invalidated">已失效</option>
          <option value="closed">已关闭</option>
          <option value="archived">已归档</option>
        </select>
        <button type="button" class="compact-button" @click="refreshAll">
          <Search :size="15" />
          筛选
        </button>
      </div>
    </SectionPanel>

    <EmptyState v-if="loading" state="loading" :message="`正在读取 ${targetLabel} AI建议信号`" />
    <EmptyState v-else-if="error" state="error" :message="error" />
    <div v-else-if="hasStaleAnalysisTarget" class="stale-target-state">
      <EmptyState state="empty" :message="staleAnalysisMessage" />
      <button type="button" class="compact-button" @click="refreshAll">
        <RefreshCw :size="15" />
        重新生成
      </button>
    </div>

    <template v-else-if="displayData">
      <div class="grid metrics ai-signal-stats">
        <MetricCard label="信号数" :value="String(signalStats.total)" :detail="targetDetail" severity="success" />
        <MetricCard label="有效信号" :value="String(signalStats.active)" detail="默认展示 active 信号" severity="success" />
        <MetricCard label="防御信号" :value="String(signalStats.defensive)" detail="减仓 / 卖出 / 回避 / 警报" severity="warning" />
        <MetricCard label="进攻信号" :value="String(signalStats.bullish)" detail="买入 / 加仓" severity="success" />
        <MetricCard label="平均置信度" :value="formatConfidence(signalStats.avgConfidence)" detail="按当前列表统计" />
        <MetricCard label="风险等级" :value="formatRiskLevel(displayData.risk_level)" :detail="formatMarketRegime(displayData.market_regime)" severity="warning" />
      </div>

      <SectionPanel title="按币种查询最新信号" note="直接生成该交易对最新 active 信号">
        <div class="panel-body ai-latest-search">
          <input
            v-model="latestSymbolQuery"
            type="text"
            :placeholder="latestSearchPlaceholder"
            @keyup.enter="searchLatestSignal"
          />
          <button type="button" class="compact-button" :disabled="latestSignalLoading" @click="searchLatestSignal">
            <Search :size="15" />
            {{ latestSignalLoading ? '查询中' : '查询最新' }}
          </button>
          <span v-if="latestSignalError" class="inline-status negative">{{ latestSignalError }}</span>
        </div>
      </SectionPanel>

      <div class="ai-signal-count">共 {{ filteredSignals.length }} 条信号</div>

      <EmptyState
        v-if="filteredSignals.length === 0"
        state="empty"
        message="当前筛选条件下没有可展示的 AI 建议信号"
      />

      <div v-else class="ai-signal-list">
        <article
          v-for="signal in filteredSignals"
          :key="signal.signal_id"
          class="ai-signal-card"
          :class="{ selected: selectedSignalDisplay?.signal_id === signal.signal_id }"
        >
          <header class="ai-signal-card__head">
            <div>
              <div class="ai-signal-badges">
                <span class="signal-pill" :class="actionTone(signal.action)">{{ actionLabel(signal.action, signal.action_label) }}</span>
                <span class="signal-pill" :class="statusTone(signal.status)">{{ statusLabel(signal.status) }}</span>
                <span class="signal-code">{{ signal.symbol }}</span>
              </div>
              <h2>{{ signal.symbol === 'MARKET' ? '全市场' : signal.symbol }}</h2>
            </div>
            <div class="ai-signal-card__meta">
              <span>{{ signal.market.toUpperCase() }}</span>
              <span>{{ formatDateTime(signal.created_at) }}</span>
            </div>
          </header>

          <div class="signal-metrics">
            <div>
              <span>评分</span>
              <strong>{{ formatNumber(signal.score) }}</strong>
            </div>
            <div>
              <span>置信度</span>
              <strong>{{ formatConfidence(signal.confidence) }}</strong>
            </div>
            <div>
              <span>周期</span>
              <strong>{{ horizonLabel(signal.horizon) }}</strong>
            </div>
          </div>

          <div class="signal-price-plan">
            <div>
              <span>入场区间</span>
              <strong>{{ formatEntryRange(signal) }}</strong>
            </div>
            <div>
              <span>止损</span>
              <strong class="negative">{{ formatNumber(signal.stop_loss) }}</strong>
            </div>
            <div>
              <span>目标价</span>
              <strong class="positive">{{ formatNumber(signal.target_price) }}</strong>
            </div>
          </div>

          <div class="signal-text-stack">
            <div v-if="signal.reason" class="signal-text-block">
              <span>理由</span>
              <p>{{ signal.reason }}</p>
            </div>
            <div v-if="signal.catalyst_summary" class="signal-text-block info">
              <span>催化</span>
              <p>{{ signal.catalyst_summary }}</p>
            </div>
            <div v-if="signal.watch_conditions" class="signal-text-block">
              <span>观察条件</span>
              <p>{{ signal.watch_conditions }}</p>
            </div>
            <div v-if="signal.risk_summary" class="signal-text-block warning">
              <span>风险</span>
              <p>{{ signal.risk_summary }}</p>
            </div>
          </div>

          <footer class="ai-signal-card__foot">
            <span>计划质量：{{ planQualityLabel(signal.plan_quality) }}</span>
            <span>阶段：{{ marketPhaseLabel(signal.market_phase) }}</span>
            <span>过期：{{ signal.expires_at ? formatDateTime(signal.expires_at) : '-' }}</span>
            <button type="button" class="compact-button" @click="selectSignal(signal)">
              <PanelRightOpen :size="14" />
              查看详情
            </button>
          </footer>
        </article>
      </div>

      <div class="grid two">
        <SectionPanel title="AI分析依据" :note="`${formatProvider(displayData.provider)} / ${displayData.model}`">
          <div class="panel-body">
            <table class="data-table">
              <tbody>
                <tr v-for="item in displayData.rationale" :key="item">
                  <td>{{ formatMessage(item) }}</td>
                  <td><StatusBadge :label="rationaleStatus.label" :tone="rationaleStatus.tone" /></td>
                </tr>
              </tbody>
            </table>
          </div>
        </SectionPanel>

        <SectionPanel title="结构化结果" :note="formatDateTime(displayData.updated_at)">
          <pre class="json-block">{{ payload }}</pre>
        </SectionPanel>
      </div>

      <SectionPanel
        title="新闻情绪"
        :note="newsData ? `${targetLabel} / ${formatStatus(newsData.status)} / ${formatDateTime(newsData.generated_at)}` : '按需读取'"
      >
        <template #actions>
          <button type="button" class="compact-button" :disabled="refreshingNews" @click="refreshNews">
            <RefreshCw :size="14" />
            {{ refreshingNews ? '刷新中' : '刷新新闻' }}
          </button>
        </template>

        <EmptyState v-if="newsLoading" state="loading" message="正在抓取新闻情绪" />
        <EmptyState v-else-if="newsError" state="error" :message="newsError" />
        <div v-else-if="newsData" class="panel-body">
          <table class="data-table">
            <tbody>
              <tr>
                <th>分析对象</th>
                <td>{{ newsData.symbol }}</td>
                <th>情绪</th>
                <td><StatusBadge :label="formatStatus(newsData.sentiment_label)" :tone="newsStatusTone" /></td>
              </tr>
              <tr>
                <th>情绪分</th>
                <td>{{ newsData.sentiment_score.toFixed(2) }}</td>
                <th>风险</th>
                <td>{{ formatRiskLevel(newsData.risk_level) }}</td>
              </tr>
              <tr>
                <th>事件风险</th>
                <td>{{ formatBoolean(newsData.event_risk) }}</td>
                <th>覆盖</th>
                <td>{{ newsData.article_count }} 条 / {{ newsData.source_count }} 个来源</td>
              </tr>
              <tr v-if="newsData.message">
                <th>状态</th>
                <td colspan="3">{{ formatMessage(newsData.message) }}</td>
              </tr>
            </tbody>
          </table>

          <table v-if="newsData.articles.length" class="data-table news-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>来源</th>
                <th>标题</th>
                <th>情绪</th>
                <th>关键词</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="article in newsData.articles" :key="article.url || article.title">
                <td>{{ article.published_at ? formatDateTime(article.published_at) : '-' }}</td>
                <td>{{ article.source }}</td>
                <td>
                  <a class="table-link" :href="article.url" target="_blank" rel="noreferrer">
                    {{ article.title }}
                  </a>
                  <div v-if="article.summary" class="muted-line">{{ article.summary }}</div>
                </td>
                <td>
                  {{ article.sentiment_score.toFixed(2) }}
                  ·
                  {{ formatStatus(article.sentiment_label) }}
                </td>
                <td>{{ article.matched_keywords.length ? article.matched_keywords.join(', ') : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else state="empty" message="点击刷新新闻读取最新情绪" />
      </SectionPanel>

      <SectionPanel title="结构校验" note="英文字段 / 英文枚举">
        <div class="panel-body grid">
          <textarea v-model="validationInput" class="json-input" spellcheck="false" />
          <div class="toolbar-row">
            <button type="button" class="primary-button" :disabled="validating" @click="validatePayload">
              <CheckCircle2 :size="15" />
              {{ validating ? '校验中' : '校验结构化内容' }}
            </button>
            <span v-if="validationError" class="inline-status negative">{{ validationError }}</span>
            <span v-else-if="validatedAnalysis" class="inline-status">
              {{ formatRiskLevel(validatedAnalysis.risk_level) }} ·
              {{ formatAction(validatedAnalysis.allowed_direction) }} ·
              {{ validatedAnalysis.decision_signal?.action_label ?? '无信号' }}
            </span>
          </div>
        </div>
      </SectionPanel>
    </template>

    <div v-if="selectedSignalDisplay" class="signal-drawer-backdrop" @click.self="selectedSignal = null">
      <aside class="signal-drawer" aria-label="信号详情">
        <header class="signal-drawer__head">
          <div>
            <span class="signal-drawer__label">信号详情</span>
            <h2>信号详情</h2>
          </div>
          <button type="button" class="signal-close-button" aria-label="关闭详情" @click="selectedSignal = null">
            <X :size="19" />
          </button>
        </header>

        <div class="signal-drawer__body">
          <div class="signal-detail-title">
            <div>
              <div class="ai-signal-badges">
                <span class="signal-pill" :class="actionTone(selectedSignalDisplay.action)">
                  {{ actionLabel(selectedSignalDisplay.action, selectedSignalDisplay.action_label) }}
                </span>
                <span class="signal-pill" :class="statusTone(selectedSignalDisplay.status)">
                  {{ statusLabel(selectedSignalDisplay.status) }}
                </span>
              </div>
              <h3>{{ selectedSignalDisplay.symbol === 'MARKET' ? '全市场' : selectedSignalDisplay.symbol }}</h3>
              <p>{{ selectedSignalDisplay.symbol }} · {{ selectedSignalDisplay.market.toUpperCase() }}</p>
            </div>
          </div>

          <div class="signal-detail-grid">
            <div>
              <span>评分</span>
              <strong>{{ formatNumber(selectedSignalDisplay.score) }}</strong>
            </div>
            <div>
              <span>置信度</span>
              <strong>{{ formatConfidence(selectedSignalDisplay.confidence) }}</strong>
            </div>
            <div>
              <span>周期</span>
              <strong>{{ horizonLabel(selectedSignalDisplay.horizon) }}</strong>
            </div>
            <div>
              <span>计划质量</span>
              <strong>{{ planQualityLabel(selectedSignalDisplay.plan_quality) }}</strong>
            </div>
            <div>
              <span>阶段</span>
              <strong>{{ marketPhaseLabel(selectedSignalDisplay.market_phase) }}</strong>
            </div>
            <div>
              <span>来源报告</span>
              <strong>{{ selectedSignalDisplay.source_report_id ?? '-' }}</strong>
            </div>
            <div>
              <span>创建时间</span>
              <strong>{{ formatDateTime(selectedSignalDisplay.created_at) }}</strong>
            </div>
            <div>
              <span>过期时间</span>
              <strong>{{ selectedSignalDisplay.expires_at ? formatDateTime(selectedSignalDisplay.expires_at) : '-' }}</strong>
            </div>
          </div>

          <section class="signal-detail-panel">
            <h3>价格计划</h3>
            <div class="signal-detail-grid three">
              <div>
                <span>入场区间</span>
                <strong>{{ formatEntryRange(selectedSignalDisplay) }}</strong>
              </div>
              <div>
                <span>止损</span>
                <strong class="negative">{{ formatNumber(selectedSignalDisplay.stop_loss) }}</strong>
              </div>
              <div>
                <span>目标价</span>
                <strong class="positive">{{ formatNumber(selectedSignalDisplay.target_price) }}</strong>
              </div>
            </div>
          </section>

          <div class="signal-detail-tabs" role="tablist" aria-label="详情视图">
            <button type="button" :class="{ active: detailTab === 'summary' }" @click="detailTab = 'summary'">
              <Activity :size="14" />
              摘要
            </button>
            <button type="button" :class="{ active: detailTab === 'evidence' }" @click="detailTab = 'evidence'">
              <Clipboard :size="14" />
              证据
            </button>
            <button type="button" :class="{ active: detailTab === 'quality' }" @click="detailTab = 'quality'">
              <Database :size="14" />
              数据质量
            </button>
            <button type="button" :class="{ active: detailTab === 'metadata' }" @click="detailTab = 'metadata'">
              <FileJson :size="14" />
              元数据
            </button>
          </div>

          <section v-if="detailTab === 'summary'" class="signal-detail-panel">
            <div class="signal-text-stack">
              <div v-if="selectedSignalDisplay.reason" class="signal-text-block">
                <span>理由</span>
                <p>{{ selectedSignalDisplay.reason }}</p>
              </div>
              <div v-if="selectedSignalDisplay.catalyst_summary" class="signal-text-block info">
                <span>催化</span>
                <p>{{ selectedSignalDisplay.catalyst_summary }}</p>
              </div>
              <div v-if="selectedSignalDisplay.watch_conditions" class="signal-text-block">
                <span>观察条件</span>
                <p>{{ selectedSignalDisplay.watch_conditions }}</p>
              </div>
              <div v-if="selectedSignalDisplay.risk_summary" class="signal-text-block warning">
                <span>风险</span>
                <p>{{ selectedSignalDisplay.risk_summary }}</p>
              </div>
              <div v-if="selectedSignalDisplay.invalidation" class="signal-text-block danger">
                <span>失效条件</span>
                <p>{{ selectedSignalDisplay.invalidation }}</p>
              </div>
            </div>
          </section>

          <section v-else-if="detailTab === 'evidence'" class="signal-detail-panel">
            <pre class="json-block drawer-json">{{ formatJson(selectedSignalDisplay.evidence) }}</pre>
          </section>

          <section v-else-if="detailTab === 'quality'" class="signal-detail-panel">
            <pre class="json-block drawer-json">{{ formatJson(selectedSignalDisplay.data_quality_summary) }}</pre>
          </section>

          <section v-else class="signal-detail-panel">
            <pre class="json-block drawer-json">{{ formatJson(selectedSignalDisplay.metadata) }}</pre>
          </section>
        </div>
      </aside>
    </div>
  </div>
</template>
