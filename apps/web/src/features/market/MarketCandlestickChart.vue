<script setup lang="ts">
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from 'lightweight-charts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { Candle } from '../../shared/types/workbench'

const props = defineProps<{
  candles: Candle[]
  resetKey: string
  emptyMessage?: string
  loadingEarlier?: boolean
  hasMoreHistory?: boolean
}>()

const emit = defineEmits<{
  loadEarlier: []
}>()

const container = ref<HTMLDivElement | null>(null)
const drawableCandleCount = ref(0)

let chart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null
let visibleRangeInitialized = false
let lastLoadEarlierAt = 0
let previousCandleTimes: UTCTimestamp[] = []

const hasDrawableCandles = computed(() => drawableCandleCount.value > 0)
const emptyMessage = computed(() =>
  props.emptyMessage ?? (props.candles.length > 0 ? 'K 线数据格式异常，无法绘制' : '暂无 K 线数据'),
)
const beijingDateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})
const beijingDateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
})
const beijingTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

function toTimestamp(timestamp: string): UTCTimestamp {
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp
}

function toDate(time: UTCTimestamp | number) {
  return new Date(Number(time) * 1000)
}

function formatBeijingDateTime(time: UTCTimestamp | number) {
  return beijingDateTimeFormatter.format(toDate(time))
}

function formatBeijingTick(time: UTCTimestamp | number, tickMarkType?: number) {
  if (tickMarkType !== undefined && tickMarkType >= 50) {
    return beijingDateFormatter.format(toDate(time))
  }

  return beijingTimeFormatter.format(toDate(time))
}

function normalizeCandles(candles: Candle[]) {
  const normalized = candles
    .map((candle) => ({
      ...candle,
      time: toTimestamp(candle.timestamp),
    }))
    .filter(
      (candle) =>
        Number.isFinite(candle.time) &&
        Number.isFinite(candle.open) &&
        Number.isFinite(candle.high) &&
        Number.isFinite(candle.low) &&
        Number.isFinite(candle.close) &&
        candle.high >= candle.low,
    )
    .sort((a, b) => a.time - b.time)

  return normalized.filter((candle, index) => normalized[index + 1]?.time !== candle.time)
}

function syncData() {
  if (!candleSeries || !volumeSeries) {
    return
  }

  const previousVisibleRange = chart?.timeScale().getVisibleLogicalRange()
  const previousFirstTime = previousCandleTimes[0]
  const normalized = normalizeCandles(props.candles)
  drawableCandleCount.value = normalized.length
  const candleTimes = normalized.map((candle) => candle.time)
  const prependedCount =
    previousVisibleRange && previousFirstTime !== undefined
      ? candleTimes.findIndex((time) => time === previousFirstTime)
      : -1
  const candleData: CandlestickData<UTCTimestamp>[] = normalized.map((candle) => ({
    time: candle.time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  }))
  const volumeData: HistogramData<UTCTimestamp>[] = normalized.map((candle) => ({
    time: candle.time,
    value: candle.volume,
    color: candle.close >= candle.open ? 'rgba(15, 159, 110, 0.28)' : 'rgba(217, 72, 84, 0.28)',
  }))

  candleSeries.setData(candleData)
  volumeSeries.setData(volumeData)

  if (chart && candleData.length > 0 && !visibleRangeInitialized) {
    const lastIndex = candleData.length - 1
    chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, lastIndex - 120),
      to: lastIndex + 5,
    })
    visibleRangeInitialized = true
  } else if (chart && previousVisibleRange && prependedCount > 0) {
    chart.timeScale().setVisibleLogicalRange({
      from: previousVisibleRange.from + prependedCount,
      to: previousVisibleRange.to + prependedCount,
    })
  }

  previousCandleTimes = candleTimes
}

function handleVisibleLogicalRangeChange(range: LogicalRange | null) {
  if (!range || !candleSeries || props.loadingEarlier || props.hasMoreHistory === false) {
    return
  }

  const barsInfo = candleSeries.barsInLogicalRange(range)
  if (!barsInfo || barsInfo.barsBefore === null || barsInfo.barsBefore > 30) {
    return
  }

  const now = Date.now()
  if (now - lastLoadEarlierAt < 800) {
    return
  }
  lastLoadEarlierAt = now
  emit('loadEarlier')
}

function resizeChart() {
  if (!chart || !container.value) {
    return
  }

  chart.applyOptions({
    width: container.value.clientWidth,
    height: container.value.clientHeight,
  })
}

function getCssVariable(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function applyChartTheme() {
  if (!chart) {
    return
  }

  const surface = getCssVariable('--surface') || '#ffffff'
  const muted = getCssVariable('--muted') || '#667789'
  const line = getCssVariable('--line') || 'rgba(102, 119, 137, 0.24)'
  const grid = getCssVariable('--chart-grid') || 'rgba(23, 33, 43, 0.06)'

  chart.applyOptions({
    layout: {
      background: { type: ColorType.Solid, color: surface },
      textColor: muted,
      fontSize: 11,
    },
    grid: {
      vertLines: { color: grid },
      horzLines: { color: grid },
    },
    rightPriceScale: {
      borderColor: line,
    },
    timeScale: {
      borderColor: line,
    },
  })
}

onMounted(async () => {
  await nextTick()

  if (!container.value) {
    return
  }

  chart = createChart(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: getCssVariable('--surface') || '#ffffff' },
      textColor: getCssVariable('--muted') || '#667789',
      fontSize: 11,
    },
    localization: {
      locale: 'zh-CN',
      timeFormatter: formatBeijingDateTime,
    },
    grid: {
      vertLines: { color: getCssVariable('--chart-grid') || 'rgba(23, 33, 43, 0.06)' },
      horzLines: { color: getCssVariable('--chart-grid') || 'rgba(23, 33, 43, 0.06)' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: getCssVariable('--line') || 'rgba(102, 119, 137, 0.24)',
      scaleMargins: {
        top: 0.08,
        bottom: 0.25,
      },
    },
    timeScale: {
      borderColor: getCssVariable('--line') || 'rgba(102, 119, 137, 0.24)',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 3,
      barSpacing: 9,
      tickMarkFormatter: formatBeijingTick,
    },
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#0f9f6e',
    downColor: '#d94854',
    wickUpColor: '#0f9f6e',
    wickDownColor: '#d94854',
    borderVisible: false,
    priceLineColor: 'rgba(15, 159, 110, 0.64)',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: {
      type: 'volume',
    },
    priceScaleId: '',
    priceLineVisible: false,
    lastValueVisible: false,
  })
  volumeSeries.priceScale().applyOptions({
    scaleMargins: {
      top: 0.78,
      bottom: 0,
    },
  })

  resizeObserver = new ResizeObserver(resizeChart)
  resizeObserver.observe(container.value)
  themeObserver = new MutationObserver(applyChartTheme)
  themeObserver.observe(document.documentElement, {
    attributeFilter: ['data-theme'],
    attributes: true,
  })
  applyChartTheme()
  chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange)
  syncData()
})

watch(
  () => props.candles,
  () => syncData(),
  { deep: true },
)

watch(
  () => props.resetKey,
  () => {
    visibleRangeInitialized = false
    lastLoadEarlierAt = 0
    previousCandleTimes = []
    syncData()
  },
)

onBeforeUnmount(() => {
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange)
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  chart?.remove()
  resizeObserver = null
  themeObserver = null
  chart = null
  candleSeries = null
  volumeSeries = null
})
</script>

<template>
  <div class="market-chart-shell">
    <div ref="container" class="market-chart" />
    <div v-if="!hasDrawableCandles" class="market-chart-empty">{{ emptyMessage }}</div>
  </div>
</template>
