<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../../shared/api/client'
import { formatDataIntegrity, formatExchange, formatMarketPrice, formatTimeframe } from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MarketSymbolPicker from '../../shared/components/MarketSymbolPicker.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import { useMarketSymbols, type ExchangeId } from '../../shared/config/markets'
import type { Candle, MarketOverview } from '../../shared/types/workbench'
import MarketCandlestickChart from './MarketCandlestickChart.vue'

const symbol = ref('BTC/USDT')
const timeframe = ref('1h')
const exchange = ref<ExchangeId>('binance')
const candleLimit = 300
const loadingEarlier = ref(false)
const loadEarlierError = ref('')
const hasMoreHistory = ref(true)

const {
  isMarketSymbolSupported,
  firstMarketSymbolForExchange,
} = useMarketSymbols(exchange)
const query = computed(() => ({
  symbol: symbol.value,
  timeframe: timeframe.value,
  exchange: exchange.value,
  limit: candleLimit,
}))

const selectedQueryLabel = computed(() => `${symbol.value} / ${formatTimeframe(timeframe.value)} / ${formatExchange(exchange.value)}`)
const responseMatchesSelection = computed(
  () =>
    data.value?.symbol === symbol.value &&
    data.value.timeframe === timeframe.value &&
    data.value.exchange === exchange.value,
)
const displayData = computed(() => (responseMatchesSelection.value ? data.value : null))
const earliestCandleTimestamp = computed(() => displayData.value?.candles[0]?.timestamp ?? null)
const isRefreshingSelection = computed(() => loading.value || (data.value !== null && !responseMatchesSelection.value))
const chartResetKey = computed(
  () => displayData.value
    ? `${displayData.value.symbol}:${displayData.value.timeframe}:${displayData.value.exchange}`
    : `${symbol.value}:${timeframe.value}:${exchange.value}:${candleLimit}`,
)
const marketDataWarning = computed(() => {
  if (!displayData.value) {
    return null
  }

  if (displayData.value.data_integrity.startsWith('exchange_error:')) {
    return formatDataIntegrity(displayData.value.data_integrity)
  }

  if (displayData.value.candles.length === 0) {
    return `${formatExchange(displayData.value.exchange)} 暂无 ${displayData.value.symbol} ${formatTimeframe(displayData.value.timeframe)} K 线数据`
  }

  return null
})
const dataQualitySeverity = computed(() => (marketDataWarning.value ? 'warning' : 'success'))

const { data, loading, error, refresh } = useResource(() => api.getMarketOverview({
  ...query.value,
}), {
  refreshIntervalMs: 30_000,
})

function mergeCandles(existing: Candle[], incoming: Candle[]) {
  const merged = new Map<string, Candle>()
  existing.forEach((candle) => merged.set(candle.timestamp, candle))
  incoming.forEach((candle) => merged.set(candle.timestamp, candle))
  return Array.from(merged.values()).sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  )
}

function isSameMarketOverview(left: MarketOverview, right: MarketOverview) {
  return left.symbol === right.symbol && left.timeframe === right.timeframe && left.exchange === right.exchange
}

async function loadEarlierCandles() {
  if (loadingEarlier.value || !displayData.value || !earliestCandleTimestamp.value || !hasMoreHistory.value) {
    return
  }

  loadingEarlier.value = true
  loadEarlierError.value = ''
  try {
    const older = await api.getMarketOverview({
      ...query.value,
      before: earliestCandleTimestamp.value,
      fast: true,
    })
    if (!data.value || !responseMatchesSelection.value) {
      return
    }

    if (older.candles.length === 0) {
      hasMoreHistory.value = false
      return
    }

    const mergedCandles = mergeCandles(data.value.candles, older.candles)
    if (mergedCandles.length === data.value.candles.length) {
      hasMoreHistory.value = false
      return
    }

    data.value = {
      ...data.value,
      candles: mergedCandles,
    } satisfies MarketOverview
  } catch (err) {
    loadEarlierError.value = err instanceof Error ? err.message : '加载更早 K 线失败'
  } finally {
    loadingEarlier.value = false
  }
}

watch(query, () => {
  hasMoreHistory.value = true
  loadEarlierError.value = ''
  void refresh()
})

let preservingLoadedHistory = false
watch(data, (current, previous) => {
  if (preservingLoadedHistory || !current || !previous || !isSameMarketOverview(current, previous)) {
    return
  }

  const mergedCandles = mergeCandles(previous.candles, current.candles)
  if (mergedCandles.length <= current.candles.length) {
    return
  }

  preservingLoadedHistory = true
  data.value = {
    ...current,
    candles: mergedCandles,
  } satisfies MarketOverview
  preservingLoadedHistory = false
})

watch(exchange, () => {
  if (!isMarketSymbolSupported(symbol.value, exchange.value)) {
    symbol.value = firstMarketSymbolForExchange(exchange.value)
  }
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">行情</h1>
        <p class="page-subtitle">查看现货行情、周期、数据源、指标和数据完整性。</p>
      </div>
      <div class="filters">
        <MarketSymbolPicker v-model="symbol" :exchange="exchange" />
        <select v-model="timeframe">
          <option value="1m">1 分钟</option>
          <option value="5m">5 分钟</option>
          <option value="15m">15 分钟</option>
          <option value="1h">1 小时</option>
          <option value="4h">4 小时</option>
          <option value="1d">1 天</option>
        </select>
        <select v-model="exchange">
          <option value="binance">币安</option>
          <option value="okx">OKX</option>
        </select>
      </div>
    </header>

    <EmptyState v-if="isRefreshingSelection" state="loading" :message="`正在加载 ${selectedQueryLabel} 行情数据`" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <template v-else-if="displayData">
      <div class="grid metrics">
        <MetricCard label="最新价" :value="formatMarketPrice(displayData.last_price)" :detail="`${displayData.symbol} ${formatExchange(displayData.exchange)}`" severity="success" />
        <MetricCard label="24h 涨跌" :value="`${displayData.change_24h_percent}%`" detail="现货市场" severity="success" />
        <MetricCard label="成交量" :value="displayData.volume_24h.toLocaleString()" detail="24 小时基础成交量" />
        <MetricCard label="波动率" :value="`${(displayData.volatility * 100).toFixed(2)}%`" detail="已实现波动率" severity="warning" />
        <MetricCard label="强弱指标" :value="displayData.rsi.toFixed(1)" detail="均线 / 平滑异同指标待叠加" />
        <MetricCard label="数据质量" :value="formatDataIntegrity(displayData.data_integrity)" :detail="`延迟 ${displayData.data_latency_seconds} 秒`" :severity="dataQualitySeverity" />
      </div>

      <SectionPanel title="K 线图 + 成交量 + 指标叠加" :note="`${displayData.symbol} / ${formatTimeframe(displayData.timeframe)} / ${formatExchange(displayData.exchange)} / ${displayData.candles.length} 根 K 线`">
        <div class="panel-body">
          <div class="chart-box">
            <MarketCandlestickChart
              :candles="displayData.candles"
              :reset-key="chartResetKey"
              :empty-message="marketDataWarning ?? undefined"
              :loading-earlier="loadingEarlier"
              :has-more-history="hasMoreHistory"
              @load-earlier="loadEarlierCandles"
            />
          </div>
          <div v-if="marketDataWarning" class="market-data-warning">{{ marketDataWarning }}</div>
          <div v-else-if="loadingEarlier" class="market-data-warning">正在加载更早 K 线</div>
          <div v-else-if="loadEarlierError" class="market-data-warning">{{ loadEarlierError }}</div>
        </div>
      </SectionPanel>

      <SectionPanel title="行情表" note="缺失 K 线、延迟、异常价格需要明确提示">
        <table class="data-table">
          <thead>
            <tr>
              <th>价格</th>
              <th>涨跌幅</th>
              <th>成交量</th>
              <th>波动率</th>
              <th>强弱指标</th>
              <th>数据状态</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ formatMarketPrice(displayData.last_price) }}</td>
              <td class="positive">{{ displayData.change_24h_percent }}%</td>
              <td>{{ displayData.volume_24h.toLocaleString() }}</td>
              <td>{{ (displayData.volatility * 100).toFixed(2) }}%</td>
              <td>{{ displayData.rsi.toFixed(1) }}</td>
              <td><StatusBadge :label="formatDataIntegrity(displayData.data_integrity)" :tone="marketDataWarning ? 'warning' : 'success'" /></td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>
    </template>
  </div>
</template>
