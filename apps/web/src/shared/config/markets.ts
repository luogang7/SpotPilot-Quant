import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'

export type ExchangeId = 'binance' | 'okx'

export interface MarketSymbolOption {
  symbol: string
  exchanges: readonly ExchangeId[]
  builtIn: boolean
}

export type CustomMarketSymbolDraft = {
  symbol: string
  exchanges: readonly ExchangeId[]
}

const CUSTOM_MARKET_SYMBOLS_STORAGE_KEY = 'spotpilot-quant.custom-market-symbols.v1'
const ALL_EXCHANGES: readonly ExchangeId[] = ['binance', 'okx']
const KNOWN_QUOTES = ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB', 'OKB'] as const
const customMarketSymbols = ref<MarketSymbolOption[]>([])

export const BUILT_IN_MARKET_SYMBOL_OPTIONS: readonly MarketSymbolOption[] = [
  { symbol: 'BTC/USDT', exchanges: ALL_EXCHANGES, builtIn: true },
  { symbol: 'ETH/USDT', exchanges: ALL_EXCHANGES, builtIn: true },
  { symbol: 'SOL/USDT', exchanges: ALL_EXCHANGES, builtIn: true },
  { symbol: 'DOGE/USDT', exchanges: ALL_EXCHANGES, builtIn: true },
  { symbol: 'BNB/USDT', exchanges: ['binance'], builtIn: true },
  { symbol: 'OKB/USDT', exchanges: ['okx'], builtIn: true },
]

export function normalizeMarketSymbol(value: string) {
  const upper = value.trim().toUpperCase().replace(/[-_\s]+/g, '/')
  if (!upper) {
    return ''
  }

  if (upper.includes('/')) {
    const [base, quote, ...extra] = upper.split('/').filter(Boolean)
    if (!base || !quote || extra.length > 0) {
      return ''
    }
    return `${base}/${quote}`
  }

  const quote = KNOWN_QUOTES.find((item) => upper.endsWith(item) && upper.length > item.length)
  if (!quote) {
    return ''
  }
  return `${upper.slice(0, -quote.length)}/${quote}`
}

export function marketSymbolValidationMessage(value: string) {
  const symbol = normalizeMarketSymbol(value)
  if (!symbol) {
    return '请输入交易对，例如 PEPE/USDT'
  }

  const [base, quote] = symbol.split('/')
  if (!/^[A-Z0-9]{2,20}$/.test(base) || !/^[A-Z0-9]{2,12}$/.test(quote)) {
    return '交易对只支持 2-20 位英文或数字，例如 ARB/USDT'
  }

  if (base === quote) {
    return '基础币和计价币不能相同'
  }

  return ''
}

export function useMarketSymbols(exchange?: Ref<ExchangeId>) {
  ensureCustomMarketSymbolsLoaded()

  const allSymbols = computed(() => mergeSymbolOptions([
    ...BUILT_IN_MARKET_SYMBOL_OPTIONS,
    ...customMarketSymbols.value,
  ]))

  const symbolOptions = computed(() => {
    if (!exchange) {
      return allSymbols.value
    }
    return allSymbols.value.filter((option) => option.exchanges.includes(exchange.value))
  })

  const customSymbols = computed(() => customMarketSymbols.value)

  function addCustomSymbol(draft: CustomMarketSymbolDraft) {
    const symbol = normalizeMarketSymbol(draft.symbol)
    const validationError = marketSymbolValidationMessage(symbol)
    if (validationError) {
      return { ok: false as const, message: validationError }
    }

    const exchanges = normalizeExchanges(draft.exchanges)
    if (exchanges.length === 0) {
      return { ok: false as const, message: '请选择至少一个交易所' }
    }

    const existing = allSymbols.value.find((option) => option.symbol === symbol)
    if (existing?.builtIn) {
      return { ok: false as const, message: `${symbol} 已是内置币种` }
    }

    const nextCustomSymbols = customMarketSymbols.value.filter((option) => option.symbol !== symbol)
    nextCustomSymbols.push({ symbol, exchanges, builtIn: false })
    saveCustomMarketSymbols(nextCustomSymbols)
    return { ok: true as const, symbol }
  }

  function removeCustomSymbol(symbol: string) {
    const normalizedSymbol = normalizeMarketSymbol(symbol)
    const nextCustomSymbols = customMarketSymbols.value.filter((option) => option.symbol !== normalizedSymbol)
    saveCustomMarketSymbols(nextCustomSymbols)
  }

  function isMarketSymbolSupported(symbol: string, selectedExchange: ExchangeId) {
    const normalizedSymbol = normalizeMarketSymbol(symbol)
    return allSymbols.value.some((option) =>
      option.symbol === normalizedSymbol && option.exchanges.includes(selectedExchange),
    )
  }

  function firstMarketSymbolForExchange(selectedExchange: ExchangeId) {
    return allSymbols.value.find((option) => option.exchanges.includes(selectedExchange))?.symbol ?? 'BTC/USDT'
  }

  onMounted(() => {
    window.addEventListener('storage', handleMarketSymbolStorage)
  })

  onUnmounted(() => {
    window.removeEventListener('storage', handleMarketSymbolStorage)
  })

  return {
    allSymbols,
    symbolOptions,
    customSymbols,
    addCustomSymbol,
    removeCustomSymbol,
    isMarketSymbolSupported,
    firstMarketSymbolForExchange,
  }
}

function ensureCustomMarketSymbolsLoaded() {
  if (customMarketSymbols.value.length > 0 || typeof window === 'undefined') {
    return
  }
  customMarketSymbols.value = readCustomMarketSymbols()
}

function readCustomMarketSymbols() {
  if (typeof window === 'undefined') {
    return []
  }

  const rawValue = window.localStorage.getItem(CUSTOM_MARKET_SYMBOLS_STORAGE_KEY)
  if (!rawValue) {
    return []
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown
    if (!Array.isArray(parsed)) {
      return []
    }
    return mergeSymbolOptions(
      parsed.flatMap((item): MarketSymbolOption[] => {
        if (!isStoredMarketSymbolOption(item)) {
          return []
        }
        const symbol = normalizeMarketSymbol(item.symbol)
        const exchanges = normalizeExchanges(item.exchanges)
        if (!symbol || exchanges.length === 0 || marketSymbolValidationMessage(symbol)) {
          return []
        }
        return [{ symbol, exchanges, builtIn: false }]
      }),
    )
  } catch {
    return []
  }
}

function saveCustomMarketSymbols(options: MarketSymbolOption[]) {
  const normalizedOptions = mergeSymbolOptions(options).filter(
    (option) => !BUILT_IN_MARKET_SYMBOL_OPTIONS.some((builtIn) => builtIn.symbol === option.symbol),
  )
  customMarketSymbols.value = normalizedOptions
  window.localStorage.setItem(
    CUSTOM_MARKET_SYMBOLS_STORAGE_KEY,
    JSON.stringify(normalizedOptions.map(({ symbol, exchanges }) => ({ symbol, exchanges }))),
  )
}

function handleMarketSymbolStorage(event: StorageEvent) {
  if (event.key === CUSTOM_MARKET_SYMBOLS_STORAGE_KEY) {
    customMarketSymbols.value = readCustomMarketSymbols()
  }
}

function normalizeExchanges(exchanges: readonly ExchangeId[]) {
  return ALL_EXCHANGES.filter((exchange) => exchanges.includes(exchange))
}

function mergeSymbolOptions(options: readonly MarketSymbolOption[]) {
  const bySymbol = new Map<string, MarketSymbolOption>()
  for (const option of options) {
    const symbol = normalizeMarketSymbol(option.symbol)
    const exchanges = normalizeExchanges(option.exchanges)
    if (!symbol || exchanges.length === 0) {
      continue
    }
    const existing = bySymbol.get(symbol)
    bySymbol.set(symbol, {
      symbol,
      exchanges: existing
        ? normalizeExchanges([...existing.exchanges, ...exchanges])
        : exchanges,
      builtIn: Boolean(existing?.builtIn || option.builtIn),
    })
  }
  return [...bySymbol.values()]
}

function isStoredMarketSymbolOption(value: unknown): value is CustomMarketSymbolDraft {
  if (!value || typeof value !== 'object') {
    return false
  }
  const item = value as Record<string, unknown>
  return typeof item.symbol === 'string' && Array.isArray(item.exchanges)
}
