import type {
  AiAnalysis,
  AiProxyConnectionTestRequest,
  AiProxyConnectionTestResult,
  AiProxySettingsUpdateRequest,
  AuditLog,
  BacktestRequest,
  BacktestResult,
  DashboardResponse,
  DailyPushResult,
  DailyPushSettingsUpdateRequest,
  DryRunOrderRequest,
  ExchangeAccountConnectionTestRequest,
  ExchangeAccountConnectionTestResult,
  ExchangeAccountSettingsUpdateRequest,
  HistoricalDataSyncRequest,
  HistoricalDataSyncResult,
  LiveCancelOrderRequest,
  LiveOrderRequest,
  MarketOverview,
  ManualClosePositionRequest,
  NewsSentimentSummary,
  NotificationResult,
  NotificationSettingsUpdateRequest,
  NotificationTestRequest,
  Order,
  RiskStatusResponse,
  SettingsSummary,
  SystemControlState,
  SystemControlUpdateRequest,
  StrategyConfig,
  StrategySignal,
  StrategyUpdateRequest,
  TradeDecisionTrace,
  SystemStatus,
  TradingSummary,
} from '../types/workbench'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const DEFAULT_TIMEOUT_MS = 15_000

interface RequestOptions {
  timeoutMs?: number
}

interface DashboardQuery {
  refresh?: boolean
}

interface SystemStatusQuery {
  probe?: boolean
}

interface MarketOverviewQuery {
  symbol?: string
  timeframe?: string
  exchange?: string
  limit?: number
  before?: string
  refresh?: boolean
  fast?: boolean
}

interface AiAnalysisQuery {
  scope?: 'market' | 'symbol'
  symbol?: string
  exchange?: string
  refresh?: boolean
  fast?: boolean
}

interface NewsSentimentQuery {
  symbol?: string
  limit?: number
  refresh?: boolean
}

interface StrategySignalQuery {
  symbol?: string
  timeframe?: string
  exchange?: string
  limit?: number
}

type QueryParams = Partial<Record<'scope' | 'symbol' | 'exchange' | 'limit' | 'before' | 'refresh' | 'timeframe' | 'probe' | 'fast', string | number | boolean | undefined>>

function createQuery(params: QueryParams) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      query.set(key, String(value))
    }
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

function createApiHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

async function requestBlob(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<Blob> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const controller = timeoutMs ? new AbortController() : undefined
  const timeoutId = timeoutMs
    ? window.setTimeout(() => controller?.abort(), timeoutMs)
    : undefined

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: createApiHeaders(init),
      cache: 'no-store',
      signal: controller?.signal ?? init?.signal,
    })

    if (!response.ok) {
      let message = response.statusText
      try {
        const payload = (await response.json()) as { detail?: unknown }
        if (typeof payload.detail === 'string' && payload.detail.trim()) {
          message = payload.detail
        }
      } catch {
        // Keep the HTTP status text when the backend does not return JSON.
      }
      throw new Error(`接口 ${response.status}：${message}`)
    }

    return response.blob()
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('接口请求超时')
    }
    throw error
  } finally {
    if (timeoutId) {
      window.clearTimeout(timeoutId)
    }
  }
}

async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const controller = timeoutMs ? new AbortController() : undefined
  const timeoutId = timeoutMs
    ? window.setTimeout(() => controller?.abort(), timeoutMs)
    : undefined

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: createApiHeaders(init),
      cache: 'no-store',
      signal: controller?.signal ?? init?.signal,
    })

    if (!response.ok) {
      let message = response.statusText
      try {
        const payload = (await response.json()) as { detail?: unknown }
        if (typeof payload.detail === 'string' && payload.detail.trim()) {
          message = payload.detail
        }
      } catch {
        // Keep the HTTP status text when the backend does not return JSON.
      }
      throw new Error(`接口 ${response.status}：${message}`)
    }

    return response.json() as Promise<T>
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('接口请求超时')
    }
    throw error
  } finally {
    if (timeoutId) {
      window.clearTimeout(timeoutId)
    }
  }
}

export const api = {
  getSystemStatus: (query: SystemStatusQuery = {}) =>
    request<SystemStatus>(`/system/status${createQuery(query)}`),
  updateSystemControl: (payload: SystemControlUpdateRequest) =>
    request<SystemControlState>('/system/control', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getDashboard: (query: DashboardQuery = {}) =>
    request<DashboardResponse>(`/dashboard${createQuery(query)}`),
  getMarketOverview: (query: MarketOverviewQuery | string = '') =>
    request<MarketOverview>(
      `/market/overview${typeof query === 'string' ? query : createQuery(query)}`,
    ),
  syncHistoricalMarketData: (payload: HistoricalDataSyncRequest) =>
    request<HistoricalDataSyncResult>('/market/history/sync', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, { timeoutMs: 10 * 60 * 1000 }),
  getStrategies: () => request<StrategyConfig[]>('/strategies'),
  runStrategySignals: (query: StrategySignalQuery = {}) =>
    request<StrategySignal[]>(`/strategies/signals/run${createQuery(query)}`, {
      method: 'POST',
    }),
  updateStrategy: (strategyId: string, payload: StrategyUpdateRequest) =>
    request<StrategyConfig>(`/strategies/${strategyId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  runBacktest: (payload: BacktestRequest) =>
    request<BacktestResult>('/backtests/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  exportBacktest: (payload: BacktestRequest, format: 'json' | 'csv') =>
    requestBlob(`/backtests/export?format=${format}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getAiAnalysis: (query: AiAnalysisQuery = {}) =>
    request<AiAnalysis>(`/ai-analysis/latest${createQuery(query)}`),
  getNewsSentiment: (query: NewsSentimentQuery | string = '') =>
    request<NewsSentimentSummary>(
      `/ai-analysis/news${typeof query === 'string' ? query : createQuery(query)}`,
    ),
  validateAiPayload: (payload: Record<string, unknown>) =>
    request<AiAnalysis>('/ai-analysis/validate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getTradingSummary: () => request<TradingSummary>('/trading/summary'),
  createDryRunOrder: (payload: DryRunOrderRequest) =>
    request<Order>('/trading/dry-run/orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createLiveOrder: (payload: LiveOrderRequest) =>
    request<Order>('/trading/live/orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelLiveOrder: (payload: LiveCancelOrderRequest) =>
    request<Order>('/trading/live/orders/cancel', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  closeLivePosition: (payload: ManualClosePositionRequest) =>
    request<Order>('/trading/live/positions/close', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getTradeDecisionTrace: (correlationId: string) =>
    request<TradeDecisionTrace>(`/trading/traces/${encodeURIComponent(correlationId)}`),
  getRiskStatus: () => request<RiskStatusResponse>('/risk/status'),
  getLogs: (limit = 20) => request<AuditLog[]>(`/logs?limit=${limit}`),
  getSettingsSummary: () => request<SettingsSummary>('/settings/summary'),
  updateAiProxySettings: (payload: AiProxySettingsUpdateRequest) =>
    request<SettingsSummary>('/settings/ai-proxies', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  testAiProxyConnection: (payload: AiProxyConnectionTestRequest) =>
    request<AiProxyConnectionTestResult>('/settings/ai-proxies/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateExchangeAccountSettings: (payload: ExchangeAccountSettingsUpdateRequest) =>
    request<SettingsSummary>('/settings/exchange-accounts', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  testExchangeAccountConnection: (payload: ExchangeAccountConnectionTestRequest) =>
    request<ExchangeAccountConnectionTestResult>('/settings/exchange-accounts/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, { timeoutMs: Math.max(DEFAULT_TIMEOUT_MS, ((payload.timeout_seconds ?? 10) + 5) * 1000) }),
  updateNotificationSettings: (payload: NotificationSettingsUpdateRequest) =>
    request<SettingsSummary>('/settings/notifications', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  sendTestNotification: (payload: NotificationTestRequest) =>
    request<NotificationResult>('/settings/notifications/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, { timeoutMs: Math.max(DEFAULT_TIMEOUT_MS, ((payload.timeout_seconds ?? 10) + 5) * 1000) }),
  updateDailyPushSettings: (payload: DailyPushSettingsUpdateRequest) =>
    request<SettingsSummary>('/settings/daily-push', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  runDailyPushNotification: () =>
    request<DailyPushResult>('/settings/notifications/daily-push/run', {
      method: 'POST',
    }, { timeoutMs: 90_000 }),
}
