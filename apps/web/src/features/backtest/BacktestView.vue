<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../../shared/api/client'
import {
  formatAction,
  formatDateTime,
  formatExchange,
  formatMessage,
  formatMoney,
  formatPercent,
  formatStatus,
  formatStrategyName,
  formatTimeframe,
} from '../../shared/api/format'
import EmptyState from '../../shared/components/EmptyState.vue'
import MarketSymbolPicker from '../../shared/components/MarketSymbolPicker.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import { useResource } from '../../shared/api/useResource'
import { useMarketSymbols, type ExchangeId } from '../../shared/config/markets'
import type { BacktestRequest, BacktestResult, HistoricalDataSyncResult, StrategyConfig } from '../../shared/types/workbench'

function dateInputValue(date: Date) {
  return date.toISOString().slice(0, 10)
}

const defaultEndDate = new Date()
defaultEndDate.setDate(defaultEndDate.getDate() - 1)
const defaultStartDate = new Date(defaultEndDate)
defaultStartDate.setDate(defaultStartDate.getDate() - 90)

const request = ref<BacktestRequest>({
  symbol: 'BTC/USDT',
  strategy_id: 'ma_cross',
  exchange: 'binance',
  timeframe: '1h',
  start_date: dateInputValue(defaultStartDate),
  end_date: dateInputValue(defaultEndDate),
  initial_capital: 10000,
  fee_rate: 0.001,
  slippage_rate: 0.0005,
})

const result = ref<BacktestResult | null>(null)
const syncResult = ref<HistoricalDataSyncResult | null>(null)
const loading = ref(false)
const syncing = ref(false)
const exporting = ref<'json' | 'csv' | null>(null)
const syncSlow = ref(false)
const error = ref<string | null>(null)
const syncError = ref<string | null>(null)
const exportError = ref<string | null>(null)
const activeSyncLabel = ref('')
const {
  data: strategies,
  loading: strategiesLoading,
  error: strategiesError,
} = useResource(api.getStrategies)

const requestExchange = computed<ExchangeId>(() => request.value.exchange ?? 'binance')
const {
  isMarketSymbolSupported,
  firstMarketSymbolForExchange,
} = useMarketSymbols(requestExchange)
const requestKey = computed(() => JSON.stringify(request.value))
const resultRequestKey = computed(() => result.value ? JSON.stringify(result.value.request) : '')
const resultMatchesRequest = computed(() => result.value !== null && resultRequestKey.value === requestKey.value)
const displayResult = computed(() => (resultMatchesRequest.value ? result.value : null))
const strategyOptions = computed(() => strategies.value ?? [])
const runnableBacktestStrategies = computed(() => strategyOptions.value.filter(isBacktestRunnableStrategy))
const selectedStrategy = computed(() =>
  strategyOptions.value.find((strategy) => strategy.id === request.value.strategy_id) ?? null,
)
const selectedStrategyUnavailableReason = computed(() =>
  selectedStrategy.value ? backtestUnavailableReason(selectedStrategy.value) : '',
)
const canRunSelectedStrategy = computed(() =>
  selectedStrategy.value ? isBacktestRunnableStrategy(selectedStrategy.value) : false,
)
const resultScopeLabel = computed(() => {
  const source = displayResult.value?.request ?? request.value
  return `${formatExchange(source.exchange ?? 'binance')} ${source.symbol} ${formatTimeframe(source.timeframe ?? '1h')} ${source.start_date} 至 ${source.end_date}`
})
const equityPoints = computed(() => {
  const values = displayResult.value?.equity_curve ?? []
  if (values.length === 0) {
    return ''
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, 1)
  return values
    .map((value, index) => {
      const x = 18 + (index * 460) / Math.max(values.length - 1, 1)
      const y = 200 - ((value - min) / spread) * 160
      return `${x},${y}`
    })
    .join(' ')
})

async function runBacktest() {
  if (!canRunSelectedStrategy.value) {
    error.value = selectedStrategyUnavailableReason.value
      ? `当前策略${selectedStrategyUnavailableReason.value}，不能运行回测`
      : '请选择可回测策略'
    return
  }
  loading.value = true
  error.value = null
  try {
    result.value = await api.runBacktest(request.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '回测失败'
  } finally {
    loading.value = false
  }
}

function isBacktestRunnableStrategy(strategy: StrategyConfig) {
  return strategy.enabled && strategy.supports_backtest === true
}

function backtestUnavailableReason(strategy: StrategyConfig) {
  if (!strategy.enabled) {
    return '已停用'
  }
  if (strategy.supports_backtest !== true) {
    return '不可回测'
  }
  return ''
}

function strategyOptionLabel(strategy: StrategyConfig) {
  const reason = backtestUnavailableReason(strategy)
  return reason ? `${formatStrategyName(strategy.name)}（${reason}）` : formatStrategyName(strategy.name)
}

async function syncHistory() {
  syncing.value = true
  syncSlow.value = false
  syncError.value = null
  syncResult.value = null
  activeSyncLabel.value = `${formatExchange(request.value.exchange ?? 'binance')} ${request.value.symbol} ${formatTimeframe(request.value.timeframe ?? '1h')} ${request.value.start_date} 至 ${request.value.end_date}`
  const slowTimer = window.setTimeout(() => {
    syncSlow.value = true
  }, 15000)
  try {
    syncResult.value = await api.syncHistoricalMarketData({
      symbol: request.value.symbol,
      exchange: request.value.exchange ?? 'binance',
      timeframe: request.value.timeframe ?? '1h',
      start_date: request.value.start_date,
      end_date: request.value.end_date,
    })
  } catch (err) {
    syncError.value = err instanceof Error ? err.message : '历史行情同步失败'
  } finally {
    window.clearTimeout(slowTimer)
    syncing.value = false
    syncSlow.value = false
  }
}

async function exportBacktest(format: 'json' | 'csv') {
  exporting.value = format
  exportError.value = null
  try {
    const source = displayResult.value?.request ?? request.value
    const blob = await api.exportBacktest(source, format)
    const url = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `backtest_${source.strategy_id}_${source.symbol.replace('/', '-')}_${source.start_date}_${source.end_date}.${format}`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.URL.revokeObjectURL(url)
  } catch (err) {
    exportError.value = err instanceof Error ? err.message : '导出失败'
  } finally {
    exporting.value = null
  }
}

watch(request, () => {
  error.value = null
  exportError.value = null
}, { deep: true })

watch(requestExchange, (exchange) => {
  if (!isMarketSymbolSupported(request.value.symbol, exchange)) {
    request.value.symbol = firstMarketSymbolForExchange(exchange)
  }
})

watch(runnableBacktestStrategies, (items) => {
  if (items.length > 0 && !items.some((strategy) => strategy.id === request.value.strategy_id)) {
    request.value.strategy_id = items[0].id
  }
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">回测</h1>
        <p class="page-subtitle">用历史 K 线回放验证策略，页面展示的是模拟成交，不是真实订单。</p>
      </div>
      <div class="filters">
        <button type="button" class="ghost-button" :disabled="syncing" @click="syncHistory">
          {{ syncing ? (syncSlow ? '仍在同步' : '同步中') : '同步历史数据' }}
        </button>
        <button type="button" class="ghost-button" :disabled="loading || exporting !== null" @click="exportBacktest('json')">
          {{ exporting === 'json' ? '导出中' : '导出 JSON' }}
        </button>
        <button type="button" class="ghost-button" :disabled="loading || exporting !== null" @click="exportBacktest('csv')">
          {{ exporting === 'csv' ? '导出中' : '导出 CSV' }}
        </button>
        <button type="button" class="primary-button" :disabled="loading || !canRunSelectedStrategy" @click="runBacktest">运行回测</button>
      </div>
    </header>

    <div class="grid two">
      <SectionPanel title="回测参数" note="来自策略管理中心">
        <div class="panel-body form-grid">
          <div class="form-field">
            <MarketSymbolPicker v-model="request.symbol" :exchange="requestExchange" label="币种" />
          </div>
          <div class="form-field">
            <label>策略</label>
            <select v-model="request.strategy_id">
              <option
                v-for="strategy in strategyOptions"
                :key="strategy.id"
                :value="strategy.id"
                :disabled="!isBacktestRunnableStrategy(strategy)"
              >
                {{ strategyOptionLabel(strategy) }}
              </option>
            </select>
            <small v-if="selectedStrategyUnavailableReason" class="field-hint warning">
              {{ selectedStrategyUnavailableReason }}
            </small>
          </div>
          <div class="form-field">
            <label>交易所</label>
            <select v-model="request.exchange">
              <option value="binance">币安</option>
              <option value="okx">OKX</option>
            </select>
          </div>
          <div class="form-field">
            <label>周期</label>
            <select v-model="request.timeframe">
              <option value="1m">1 分钟</option>
              <option value="5m">5 分钟</option>
              <option value="15m">15 分钟</option>
              <option value="1h">1 小时</option>
              <option value="4h">4 小时</option>
              <option value="1d">1 天</option>
            </select>
          </div>
          <div class="form-field">
            <label>开始日期</label>
            <input v-model="request.start_date" type="date" />
          </div>
          <div class="form-field">
            <label>结束日期</label>
            <input v-model="request.end_date" type="date" />
          </div>
          <div class="form-field">
            <label>初始资金</label>
            <input v-model.number="request.initial_capital" type="number" />
          </div>
          <div class="form-field">
            <label>手续费</label>
            <input v-model.number="request.fee_rate" type="number" step="0.0001" />
          </div>
          <div class="form-field">
            <label>滑点</label>
            <input v-model.number="request.slippage_rate" type="number" step="0.0001" />
          </div>
          <div v-if="syncing || syncResult || syncError" class="result-message form-span">
            <strong>{{ syncing ? (syncSlow ? '同步较慢' : '同步中') : formatStatus(syncResult?.status ?? 'sync_error') }}</strong>
            <span v-if="syncing">
              {{ activeSyncLabel }}
              <template v-if="syncSlow"> 同步 1m 大范围数据会比较慢，请保持页面打开。</template>
            </span>
            <span v-else-if="syncResult">
              <template v-if="syncResult.status === 'completed'">
                拉取 {{ syncResult.fetched }} 根 / 新增 {{ syncResult.inserted }} 根 / 更新 {{ syncResult.updated }} 根
              </template>
              <template v-else>
                {{ formatMessage(syncResult.message) }}
              </template>
            </span>
            <span v-else>{{ syncError }}</span>
          </div>
          <div v-if="exportError" class="result-message negative form-span">
            <strong>导出失败</strong>
            <span>{{ exportError }}</span>
          </div>
          <div v-if="strategiesLoading || strategiesError" class="result-message form-span">
            <strong>{{ strategiesLoading ? '策略加载中' : '策略加载失败' }}</strong>
            <span>{{ strategiesError ?? '正在读取策略管理中心' }}</span>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel title="回测结果" :note="resultScopeLabel">
        <EmptyState v-if="loading" state="loading" message="正在运行回测" />
        <EmptyState v-else-if="error" state="error" :message="error" />
        <div v-else-if="displayResult" class="panel-body grid">
          <div class="result-message">
            <strong>{{ formatStatus(displayResult.status ?? 'completed') }}</strong>
            <span>{{ displayResult.message ? formatMessage(displayResult.message) : '历史回测模拟完成' }}</span>
          </div>
          <div class="grid three">
            <MetricCard label="模拟收益" :value="formatPercent(displayResult.total_return_percent)" detail="扣除费用后的收益" severity="success" />
            <MetricCard label="最大回撤" :value="formatPercent(displayResult.max_drawdown_percent)" detail="最大资金回落" severity="warning" />
            <MetricCard label="胜率" :value="formatPercent(displayResult.win_rate_percent, 1)" :detail="`${displayResult.trade_count} 笔模拟成交`" />
          </div>
          <div class="chart-box">
            <svg viewBox="0 0 500 230" role="img" aria-label="回测资产曲线">
              <polyline :points="equityPoints" fill="none" stroke="#43d18d" stroke-width="3" stroke-linecap="round" />
              <line class="chart-axis-line" x1="18" y1="200" x2="480" y2="200" />
            </svg>
          </div>
        </div>
        <EmptyState v-else state="empty" message="设置回测参数后点击运行回测" />
      </SectionPanel>
    </div>

    <SectionPanel v-if="displayResult" title="历史回测模拟成交" note="由历史 K 线回放生成，非真实订单">
      <table class="data-table">
        <thead>
          <tr>
            <th>开仓</th>
            <th>平仓</th>
            <th>币种</th>
            <th>方向</th>
            <th>开仓价</th>
            <th>平仓价</th>
            <th>盈亏</th>
            <th>手续费</th>
            <th>退出原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="trade in displayResult.trades" :key="`${trade.symbol}-${trade.opened_at}`">
            <td>{{ formatDateTime(trade.opened_at) }}</td>
            <td>{{ formatDateTime(trade.closed_at) }}</td>
            <td>{{ trade.symbol }}</td>
            <td>{{ formatAction(trade.side) }}</td>
            <td>{{ formatMoney(trade.entry_price, 2) }}</td>
            <td>{{ formatMoney(trade.exit_price, 2) }}</td>
            <td :class="trade.pnl >= 0 ? 'positive' : 'negative'">{{ formatMoney(trade.pnl) }}</td>
            <td>{{ formatMoney(trade.fee) }}</td>
            <td>{{ formatStatus(trade.exit_reason) }}</td>
          </tr>
        </tbody>
      </table>
    </SectionPanel>
  </div>
</template>
