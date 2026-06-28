export type TradingMode = 'dry_run' | 'live'
export type ConnectionState = 'healthy' | 'degraded' | 'offline'
export type Severity = 'info' | 'warning' | 'critical' | 'success'
export type RiskLevel = 'low' | 'medium' | 'high' | 'extreme'
export type RiskStatus = 'allow_trading' | 'reduce_only' | 'no_new_positions' | 'paused'
export type SpotSignalAction = 'buy' | 'sell_existing' | 'hold' | 'cancel_order'
export type AllowedDirection = 'long_only' | 'reduce_only' | 'both' | 'none'
export type SentimentLabel = 'positive' | 'neutral' | 'negative'
export type AiDecisionSignalAction = 'buy' | 'add' | 'hold' | 'reduce' | 'sell' | 'watch' | 'avoid' | 'alert'
export type AiDecisionSignalStatus = 'active' | 'expired' | 'invalidated' | 'closed' | 'archived'
export type AiDecisionSignalPlanQuality = 'complete' | 'partial' | 'minimal' | 'unknown'
export type AiDecisionSignalHorizon = 'intraday' | '1d' | '3d' | '5d' | '10d' | 'swing' | 'long'

export interface ExchangeStatus {
  exchange: 'binance' | 'okx'
  state: ConnectionState
  latency_ms?: number | null
  last_checked_at: string
  message: string
}

export interface AiProxyStatus {
  provider: string
  model: string
  state: ConnectionState
  priority: number
  timeout_seconds: number
  last_called_at: string
  failover_ready: boolean
}

export interface SystemStatus {
  trading_mode: TradingMode
  live_enabled: boolean
  paused: boolean
  kill_switch_armed: boolean
  data_latency_seconds?: number | null
  exchanges: ExchangeStatus[]
  ai_proxy: AiProxyStatus
}

export interface SystemControlState {
  paused: boolean
  kill_switch_armed: boolean
  updated_at: string
  reason: string
}

export interface SystemControlUpdateRequest {
  paused?: boolean | null
  kill_switch_armed?: boolean | null
  reason?: string
}

export interface Metric {
  label: string
  value: string
  detail: string
  severity: Severity
}

export interface Position {
  symbol: string
  side: string
  quantity: number
  average_price: number
  current_price: number
  unrealized_pnl: number
  stop_loss?: number | null
  take_profit?: number | null
}

export interface StrategySignal {
  occurred_at: string
  symbol: string
  strategy: string
  action: SpotSignalAction
  price: number
  reason: string
  blocked_by?: string | null
  correlation_id: string
}

export interface AiDecisionSignal {
  signal_id: string
  analysis_scope: 'market' | 'symbol' | string
  symbol: string
  market: string
  exchange?: 'binance' | 'okx' | null
  source_type: string
  source_report_id?: string | null
  trace_id?: string | null
  action: AiDecisionSignalAction
  action_label: string
  status: AiDecisionSignalStatus
  score?: number | null
  confidence?: number | null
  horizon?: AiDecisionSignalHorizon | null
  plan_quality: AiDecisionSignalPlanQuality
  market_phase: string
  entry_low?: number | null
  entry_high?: number | null
  stop_loss?: number | null
  target_price?: number | null
  invalidation?: string | null
  watch_conditions?: string | null
  reason?: string | null
  risk_summary?: string | null
  catalyst_summary?: string | null
  evidence?: Record<string, unknown>
  data_quality_summary?: Record<string, unknown>
  metadata?: Record<string, unknown>
  created_at: string
  expires_at?: string | null
}

export interface AiAnalysis {
  correlation_id?: string | null
  analysis_scope: 'market' | 'symbol' | string
  symbol?: string | null
  market_regime: string
  sentiment_score: number
  risk_level: RiskLevel
  event_risk: boolean
  allowed_direction: AllowedDirection
  confidence: number
  provider: string
  model: string
  rationale: string[]
  structured_payload: Record<string, unknown>
  decision_signal?: AiDecisionSignal | null
  updated_at: string
}

export interface NewsArticle {
  source: string
  title: string
  url: string
  published_at?: string | null
  summary: string
  symbols: string[]
  sentiment_score: number
  sentiment_label: SentimentLabel
  event_risk: boolean
  matched_keywords: string[]
}

export interface NewsSentimentSummary {
  symbol: string
  sentiment_score: number
  sentiment_label: SentimentLabel
  risk_level: RiskLevel
  event_risk: boolean
  article_count: number
  source_count: number
  status: string
  message: string
  rationale: string[]
  articles: NewsArticle[]
  generated_at: string
}

export interface AuditLog {
  occurred_at: string
  level: Severity
  module: string
  symbol?: string | null
  strategy?: string | null
  message: string
  correlation_id: string
}

export interface DashboardResponse {
  system: SystemStatus
  metrics: Metric[]
  equity_curve: number[]
  positions: Position[]
  latest_signals: StrategySignal[]
  ai: AiAnalysis
  latest_logs: AuditLog[]
}

export interface Candle {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface MarketOverview {
  symbol: string
  timeframe: string
  exchange: 'binance' | 'okx'
  last_price: number
  change_24h_percent: number
  volume_24h: number
  volatility: number
  rsi: number
  data_latency_seconds: number
  data_integrity: string
  candles: Candle[]
}

export interface StrategyConfig {
  id: string
  name: string
  enabled: boolean
  mode: string
  status: string
  parameters: Record<string, string | number | boolean>
  risk_controls: Record<string, string | number | boolean>
  recent_signals: StrategySignal[]
  family?: string
  description?: string
  supports_signals?: boolean
  supports_backtest?: boolean
  supports_live?: boolean
}

export interface StrategyUpdateRequest {
  enabled?: boolean | null
  mode?: string | null
  parameters?: Record<string, string | number | boolean> | null
  risk_controls?: Record<string, string | number | boolean> | null
}

export interface BacktestRequest {
  symbol: string
  strategy_id: string
  exchange?: 'binance' | 'okx'
  timeframe?: string
  start_date: string
  end_date: string
  initial_capital: number
  fee_rate: number
  slippage_rate: number
}

export interface HistoricalDataSyncRequest {
  symbol: string
  exchange: 'binance' | 'okx'
  timeframe: string
  start_date: string
  end_date: string
}

export interface HistoricalDataSyncResult {
  symbol: string
  exchange: 'binance' | 'okx'
  timeframe: string
  start_date: string
  end_date: string
  fetched: number
  inserted: number
  updated: number
  first_timestamp?: string | null
  last_timestamp?: string | null
  status: string
  message: string
}

export interface BacktestTrade {
  opened_at: string
  closed_at: string
  symbol: string
  side: string
  entry_price: number
  exit_price: number
  pnl: number
  fee: number
  exit_reason: string
}

export interface BacktestResult {
  request: BacktestRequest
  status?: string
  message?: string
  total_return_percent: number
  annual_return_percent: number
  max_drawdown_percent: number
  win_rate_percent: number
  profit_factor: number
  trade_count: number
  equity_curve: number[]
  trades: BacktestTrade[]
}

export interface Balance {
  asset: string
  free: number
  locked: number
  total: number
}

export interface Order {
  order_id: string
  correlation_id?: string | null
  exchange: 'binance' | 'okx'
  symbol: string
  side: string
  order_type: string
  price: number
  quantity: number
  fee?: number | null
  status: string
  created_at: string
}

export interface DryRunOrderRequest {
  symbol: string
  action: SpotSignalAction
  order_type?: string
  quantity: number
  price?: number | null
  strategy?: string | null
}

export interface LiveOrderRequest {
  exchange?: 'binance' | 'okx' | null
  symbol: string
  action: SpotSignalAction
  order_type?: string
  quantity: number
  price?: number | null
  strategy?: string | null
  client_order_id?: string | null
}

export interface LiveCancelOrderRequest {
  exchange?: 'binance' | 'okx' | null
  symbol: string
  order_id: string
}

export interface ManualClosePositionRequest {
  exchange?: 'binance' | 'okx' | null
  symbol: string
  quantity?: number | null
  order_type?: string
  price?: number | null
}

export interface TradingSummary {
  mode: TradingMode
  balances: Balance[]
  positions: Position[]
  open_orders: Order[]
  historical_orders: Order[]
  spot_only: boolean
  contract_trading_disabled: boolean
}

export interface RiskRule {
  name: string
  current_value: string
  threshold: string
  status: Severity
  action: string
}

export interface RiskEvent {
  occurred_at: string
  rule: string
  symbol: string
  trigger_value: string
  action: string
  reason: string
  correlation_id: string
}

export interface RiskStatusResponse {
  status: RiskStatus
  summary: string
  rules: RiskRule[]
  events: RiskEvent[]
}

export interface TradeDecisionTrace {
  correlation_id: string
  signal?: StrategySignal | null
  ai_analysis?: AiAnalysis | null
  risk_status?: RiskStatus | null
  risk_events: RiskEvent[]
  order?: Order | null
  logs: AuditLog[]
}

export interface NewsFeedSource {
  name: string
  website_url: string
  feed_url: string
}

export interface SettingsSummary {
  exchanges: Array<Record<string, string | boolean>>
  ai_proxies: Array<Record<string, string | number | boolean>>
  ai_provider_templates: Array<Record<string, string | boolean>>
  data: Record<string, string | number>
  news_feeds: NewsFeedSource[]
  notifications: Record<string, string | number | boolean>
  safety_checks: Array<Record<string, string>>
}

export interface AiProxySettingsUpdate {
  slot: 'A' | 'B' | 'C'
  provider: string
  base_url: string
  api_key?: string | null
  model: string
  priority: number
  enabled: boolean
  api_format: 'chat_completions' | 'responses'
}

export interface AiProxySettingsUpdateRequest {
  proxies: AiProxySettingsUpdate[]
}

export interface AiProxyConnectionTestRequest {
  proxy: AiProxySettingsUpdate
  timeout_seconds?: number
}

export interface AiProxyConnectionTestResult {
  success: boolean
  provider: string
  model: string
  message: string
  latency_ms: number
  used_saved_api_key: boolean
}

export interface ExchangeAccountSettingsUpdate {
  exchange: 'binance' | 'okx'
  api_key?: string | null
  api_secret?: string | null
  passphrase?: string | null
  spot_trading_enabled: boolean
  sandbox: boolean
}

export interface ExchangeAccountSettingsUpdateRequest {
  accounts: ExchangeAccountSettingsUpdate[]
}

export interface ExchangeAccountConnectionTestRequest {
  account: ExchangeAccountSettingsUpdate
  timeout_seconds?: number
}

export interface ExchangeAccountConnectionTestResult {
  success: boolean
  exchange: 'binance' | 'okx'
  message: string
  latency_ms: number
  used_saved_credentials: boolean
  balance_asset_count: number
}

export type NotificationProvider = 'feishu' | 'wecom' | 'telegram' | 'email' | 'slack' | 'discord'

export interface NotificationChannelSettingsUpdate {
  provider: NotificationProvider
  webhook_url?: string | null
  telegram_bot_token?: string | null
  telegram_chat_id?: string | null
  email_smtp_host?: string | null
  email_smtp_port?: number | null
  email_smtp_username?: string | null
  email_smtp_password?: string | null
  email_from?: string | null
  email_to?: string | null
  email_use_tls?: boolean | null
}

export interface NotificationSettingsUpdateRequest {
  channels: NotificationChannelSettingsUpdate[]
}

export interface NotificationTestRequest {
  provider?: NotificationProvider
  title?: string
  message: string
  timeout_seconds?: number
}

export interface NotificationResult {
  success: boolean
  provider: string
  message: string
}

export interface DailyPushResult {
  success: boolean
  title: string
  message: string
  results: NotificationResult[]
}

export interface DailyPushSettingsUpdateRequest {
  enabled: boolean
  schedule_time: string
  schedule_times: string
  run_immediately: boolean
}
