from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class TradingMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class ExchangeId(str, Enum):
    BINANCE = "binance"
    OKX = "okx"


class ConnectionState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class RiskStatus(str, Enum):
    ALLOW_TRADING = "allow_trading"
    REDUCE_ONLY = "reduce_only"
    NO_NEW_POSITIONS = "no_new_positions"
    PAUSED = "paused"


class SpotSignalAction(str, Enum):
    BUY = "buy"
    SELL_EXISTING = "sell_existing"
    HOLD = "hold"
    CANCEL_ORDER = "cancel_order"


class AllowedDirection(str, Enum):
    LONG_ONLY = "long_only"
    REDUCE_ONLY = "reduce_only"
    BOTH = "both"
    NONE = "none"


class AiDecisionSignalAction(str, Enum):
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    WATCH = "watch"
    AVOID = "avoid"
    ALERT = "alert"


class AiDecisionSignalStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    CLOSED = "closed"
    ARCHIVED = "archived"


class AiDecisionSignalPlanQuality(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MINIMAL = "minimal"
    UNKNOWN = "unknown"


class AiDecisionSignalHorizon(str, Enum):
    INTRADAY = "intraday"
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    FIVE_DAYS = "5d"
    TEN_DAYS = "10d"
    SWING = "swing"
    LONG = "long"


class NotificationProvider(str, Enum):
    FEISHU = "feishu"
    WECOM = "wecom"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SLACK = "slack"
    DISCORD = "discord"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    SUCCESS = "success"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExchangeStatus(ApiModel):
    exchange: ExchangeId
    state: ConnectionState
    latency_ms: int | None = None
    last_checked_at: datetime = Field(default_factory=utc_now)
    message: str


class AiProxyStatus(ApiModel):
    provider: str
    model: str
    state: ConnectionState
    priority: int
    timeout_seconds: int
    last_called_at: datetime = Field(default_factory=utc_now)
    failover_ready: bool


class SystemStatus(ApiModel):
    trading_mode: TradingMode
    live_enabled: bool
    paused: bool
    kill_switch_armed: bool
    data_latency_seconds: int | None = None
    exchanges: list[ExchangeStatus]
    ai_proxy: AiProxyStatus


class SystemControlState(ApiModel):
    paused: bool = False
    kill_switch_armed: bool = False
    updated_at: datetime = Field(default_factory=utc_now)
    reason: str = "initial"


class SystemControlUpdateRequest(ApiModel):
    paused: bool | None = None
    kill_switch_armed: bool | None = None
    reason: str = "manual"


class Metric(ApiModel):
    label: str
    value: str
    detail: str
    severity: Severity = Severity.INFO


class Position(ApiModel):
    symbol: str
    side: str = "long"
    quantity: float
    average_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: float | None = None
    take_profit: float | None = None


class StrategySignal(ApiModel):
    occurred_at: datetime = Field(default_factory=utc_now)
    symbol: str
    strategy: str
    action: SpotSignalAction
    price: float
    reason: str
    blocked_by: str | None = None
    correlation_id: str


class AiDecisionSignal(ApiModel):
    signal_id: str
    analysis_scope: str = "symbol"
    symbol: str
    market: str = "crypto"
    exchange: ExchangeId | None = None
    source_type: str = "ai_analysis"
    source_report_id: str | None = None
    trace_id: str | None = None
    action: AiDecisionSignalAction
    action_label: str
    status: AiDecisionSignalStatus = AiDecisionSignalStatus.ACTIVE
    score: float | None = None
    confidence: float | None = None
    horizon: AiDecisionSignalHorizon | None = None
    plan_quality: AiDecisionSignalPlanQuality = AiDecisionSignalPlanQuality.UNKNOWN
    market_phase: str = "crypto_24x7"
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    invalidation: str | None = None
    watch_conditions: str | None = None
    reason: str | None = None
    risk_summary: str | None = None
    catalyst_summary: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    data_quality_summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None


class AiAnalysis(ApiModel):
    correlation_id: str | None = None
    analysis_scope: str = "symbol"
    symbol: str | None = None
    market_regime: str
    sentiment_score: float = Field(ge=-1, le=1)
    risk_level: RiskLevel
    event_risk: bool
    allowed_direction: AllowedDirection
    confidence: float = Field(ge=0, le=1)
    provider: str
    model: str
    rationale: list[str]
    structured_payload: dict[str, Any]
    decision_signal: AiDecisionSignal | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class NewsArticle(ApiModel):
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    sentiment_score: float = Field(ge=-1, le=1)
    sentiment_label: SentimentLabel
    event_risk: bool = False
    matched_keywords: list[str] = Field(default_factory=list)


class NewsSentimentSummary(ApiModel):
    symbol: str
    sentiment_score: float = Field(ge=-1, le=1)
    sentiment_label: SentimentLabel
    risk_level: RiskLevel
    event_risk: bool = False
    article_count: int = 0
    source_count: int = 0
    status: str = "empty"
    message: str = ""
    rationale: list[str] = Field(default_factory=list)
    articles: list[NewsArticle] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class AuditLog(ApiModel):
    occurred_at: datetime = Field(default_factory=utc_now)
    level: Severity
    module: str
    symbol: str | None = None
    strategy: str | None = None
    message: str
    correlation_id: str


class DashboardResponse(ApiModel):
    system: SystemStatus
    metrics: list[Metric]
    equity_curve: list[float]
    positions: list[Position]
    latest_signals: list[StrategySignal]
    ai: AiAnalysis
    latest_logs: list[AuditLog]


class Candle(ApiModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketOverview(ApiModel):
    symbol: str
    timeframe: str
    exchange: ExchangeId
    last_price: float
    change_24h_percent: float
    volume_24h: float
    volatility: float
    rsi: float
    data_latency_seconds: int
    data_integrity: str
    candles: list[Candle]


class StrategyConfig(ApiModel):
    id: str
    name: str
    enabled: bool
    mode: str
    status: str
    parameters: dict[str, float | int | str | bool]
    risk_controls: dict[str, float | int | str | bool]
    recent_signals: list[StrategySignal]
    family: str = "custom"
    description: str = ""
    supports_signals: bool = True
    supports_backtest: bool = True
    supports_live: bool = False


class BacktestRequest(ApiModel):
    symbol: str = "BTC/USDT"
    strategy_id: str = "ma_cross"
    exchange: ExchangeId = ExchangeId.BINANCE
    timeframe: str = "1h"
    start_date: str = "2026-01-01"
    end_date: str = "2026-06-01"
    initial_capital: float = 10_000
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005


class HistoricalDataSyncRequest(ApiModel):
    symbol: str = "BTC/USDT"
    exchange: ExchangeId = ExchangeId.BINANCE
    timeframe: str = "1h"
    start_date: str = "2026-01-01"
    end_date: str = "2026-06-01"


class HistoricalDataSyncResult(ApiModel):
    symbol: str
    exchange: ExchangeId
    timeframe: str
    start_date: str
    end_date: str
    fetched: int
    inserted: int
    updated: int
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    status: str = "completed"
    message: str = ""


class BacktestTrade(ApiModel):
    opened_at: datetime
    closed_at: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    fee: float
    exit_reason: str


class BacktestResult(ApiModel):
    request: BacktestRequest
    status: str = "completed"
    message: str = ""
    total_return_percent: float
    annual_return_percent: float
    max_drawdown_percent: float
    win_rate_percent: float
    profit_factor: float
    trade_count: int
    equity_curve: list[float]
    trades: list[BacktestTrade]


class Balance(ApiModel):
    asset: str
    free: float
    locked: float
    total: float


class Order(ApiModel):
    order_id: str
    correlation_id: str | None = None
    exchange: ExchangeId = ExchangeId.BINANCE
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: float
    fee: float | None = None
    status: str
    created_at: datetime = Field(default_factory=utc_now)


class TradingSummary(ApiModel):
    mode: TradingMode
    balances: list[Balance]
    positions: list[Position]
    open_orders: list[Order]
    historical_orders: list[Order]
    spot_only: bool = True
    contract_trading_disabled: bool = True


class RiskRule(ApiModel):
    name: str
    current_value: str
    threshold: str
    status: Severity
    action: str


class RiskEvent(ApiModel):
    occurred_at: datetime = Field(default_factory=utc_now)
    rule: str
    symbol: str
    trigger_value: str
    action: str
    reason: str
    correlation_id: str


class RiskStatusResponse(ApiModel):
    status: RiskStatus
    summary: str
    rules: list[RiskRule]
    events: list[RiskEvent]


class TradeDecisionTrace(ApiModel):
    correlation_id: str
    signal: StrategySignal | None = None
    ai_analysis: AiAnalysis | None = None
    risk_status: RiskStatus | None = None
    risk_events: list[RiskEvent]
    order: Order | None = None
    logs: list[AuditLog]


class NewsFeedSource(ApiModel):
    name: str
    website_url: str
    feed_url: str


class SettingsSummary(ApiModel):
    exchanges: list[dict[str, str | bool]]
    ai_proxies: list[dict[str, str | int | bool]]
    ai_provider_templates: list[dict[str, str | bool]]
    data: dict[str, str | int]
    news_feeds: list[NewsFeedSource]
    notifications: dict[str, str | int | bool]
    safety_checks: list[dict[str, str]]


class AiProxySettingsUpdate(ApiModel):
    slot: str = Field(pattern="^[ABC]$")
    provider: str = Field(min_length=1, max_length=64)
    base_url: str = ""
    api_key: str | None = None
    model: str = Field(min_length=1, max_length=128)
    priority: int = Field(ge=1, le=99)
    enabled: bool = False
    api_format: str = Field(default="chat_completions", pattern="^(chat_completions|responses)$")


class AiProxySettingsUpdateRequest(ApiModel):
    proxies: list[AiProxySettingsUpdate] = Field(min_length=1, max_length=3)


class AiProxyConnectionTestRequest(ApiModel):
    proxy: AiProxySettingsUpdate
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class AiProxyConnectionTestResult(ApiModel):
    success: bool
    provider: str
    model: str
    message: str
    latency_ms: int
    used_saved_api_key: bool = False


class ExchangeAccountSettingsUpdate(ApiModel):
    exchange: ExchangeId
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None
    spot_trading_enabled: bool = False
    sandbox: bool = False


class ExchangeAccountSettingsUpdateRequest(ApiModel):
    accounts: list[ExchangeAccountSettingsUpdate] = Field(min_length=1, max_length=2)


class ExchangeAccountConnectionTestRequest(ApiModel):
    account: ExchangeAccountSettingsUpdate
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class ExchangeAccountConnectionTestResult(ApiModel):
    success: bool
    exchange: ExchangeId
    message: str
    latency_ms: int
    used_saved_credentials: bool = False
    balance_asset_count: int = 0


class NotificationChannelSettingsUpdate(ApiModel):
    provider: NotificationProvider
    webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int | None = Field(default=None, ge=1, le=65535)
    email_smtp_username: str | None = None
    email_smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    email_use_tls: bool | None = None


class NotificationSettingsUpdateRequest(ApiModel):
    channels: list[NotificationChannelSettingsUpdate] = Field(min_length=1, max_length=6)


class DailyPushSettingsUpdateRequest(ApiModel):
    enabled: bool
    schedule_time: str = Field(default="18:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_times: str = Field(default="", max_length=120)
    run_immediately: bool = False


class StrategyUpdateRequest(ApiModel):
    enabled: bool | None = None
    mode: str | None = None
    parameters: dict[str, float | int | str | bool] | None = None
    risk_controls: dict[str, float | int | str | bool] | None = None


class DryRunOrderRequest(ApiModel):
    symbol: str
    action: SpotSignalAction
    order_type: str = "market"
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    strategy: str | None = None


class LiveOrderRequest(ApiModel):
    exchange: ExchangeId | None = None
    symbol: str
    action: SpotSignalAction
    order_type: str = "market"
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    strategy: str | None = None
    client_order_id: str | None = None


class LiveCancelOrderRequest(ApiModel):
    exchange: ExchangeId | None = None
    symbol: str
    order_id: str


class ManualClosePositionRequest(ApiModel):
    exchange: ExchangeId | None = None
    symbol: str
    quantity: float | None = Field(default=None, gt=0)
    order_type: str = "market"
    price: float | None = Field(default=None, gt=0)


class NotificationTestRequest(ApiModel):
    provider: NotificationProvider = NotificationProvider.FEISHU
    title: str = Field(default="DSA 通知测试", max_length=120)
    message: str = "SpotPilot Quant notification test"
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class NotificationResult(ApiModel):
    success: bool
    provider: str
    message: str


class DailyPushResult(ApiModel):
    success: bool
    title: str
    message: str
    results: list[NotificationResult]
