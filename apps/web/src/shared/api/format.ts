import { currentLanguage, translateText } from '../i18n'

export function formatMoney(value: number, digits = 2) {
  return new Intl.NumberFormat(currentLanguage.value === 'zh' ? 'zh-CN' : 'en-US', {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    maximumFractionDigits: digits,
  }).format(value)
}

export function formatMarketPrice(value: number) {
  const absoluteValue = Math.abs(value)
  const digits = absoluteValue >= 10 ? 2 : absoluteValue >= 1 ? 4 : absoluteValue >= 0.01 ? 6 : 8

  return formatMoney(value, digits)
}

export function formatPercent(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`
}

export function formatDateTime(value: string) {
  const normalizedValue = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`

  return new Intl.DateTimeFormat(currentLanguage.value === 'zh' ? 'zh-CN' : 'en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(normalizedValue))
}

const STATUS_LABELS: Record<string, string> = {
  allow_trading: '允许交易',
  reduce_only: '仅允许减仓',
  no_new_positions: '当前禁止新开仓',
  paused: '策略已暂停',
  allow: '允许',
  ok: '正常',
  pause: '暂停',
  rejected_by_risk: '风控拒绝',
  rejected_no_spot_position: '现货持仓不足，无法卖出',
  validated_cancel_only: '撤单校验通过',
  validated_hold: '观望校验通过',
  validated_dry_run: '模拟校验通过',
  pending: '待处理',
  open: '挂单中',
  filled: '已成交',
  canceled: '已撤销',
  cancelled: '已撤销',
  rejected: '已拒绝',
  completed: '已完成',
  syncing: '同步中',
  syncing_slow: '同步较慢',
  sync_error: '同步失败',
  exchange_error: '交易所异常',
  empty: '暂无数据',
  fetch_error: '抓取失败',
  repository_unavailable: '本地数据库不可用',
  invalid_range: '日期范围无效',
  unsupported_strategy: '暂不支持该策略',
  strategy_not_found: '找不到策略',
  strategy_disabled: '策略已停用',
  data_unavailable: '缺少历史行情',
  invalid_parameters: '参数无效',
  ready: '可运行',
  disabled: '已停用',
  planned_p1: '后续版本支持',
  schema_validator_only: '只做结构校验',
  passed: '已通过',
  must_be_disabled: '必须关闭',
  required: '必须确认',
  enabled: '已启用',
  healthy: '连接正常',
  degraded: '部分可用',
  offline: '未连接',
  info: '提示',
  warning: '注意',
  critical: '紧急',
  success: '正常',
  positive: '正面',
  neutral: '中性',
  negative: '负面',
  sent: '已发送',
  blocked: '已拦截',
  'Kill Switch': '紧急停止',
  'Spot only': '只允许现货',
  'Contract disabled': '合约已禁用',
  'Withdraw permission': '提现权限',
  'Exchange account binding': '交易所账号绑定',
  'Live confirmation': '实盘二次确认',
  ACCOUNT: '账户',
  'N/A': '暂未接入',
}

const ACTION_LABELS: Record<string, string> = {
  buy: '买入',
  sell_existing: '卖出现货',
  hold: '观望',
  cancel_order: '撤单',
  long: '做多',
  long_only: '仅做多',
  reduce_only: '仅减仓',
  both: '双向',
  none: '禁止交易',
  market: '市价单',
  limit: '限价单',
}

const RISK_RULE_LABELS: Record<string, string> = {
  全局暂停: '全局暂停',
  账户余额来源: '账户余额来源',
  数据延迟: '数据延迟',
  单笔最大亏损: '单笔最大亏损',
  单日最大亏损: '单日最大亏损',
  最大回撤: '最大回撤',
  单币最大仓位: '单币最大仓位',
  总仓位上限: '总仓位上限',
  连续亏损暂停: '连续亏损暂停',
  'AI 高风险暂停': 'AI 高风险暂停',
}

const TRADING_MODE_LABELS: Record<string, string> = {
  dry_run: '模拟运行',
  live: '小额实盘',
  backtest_only: '仅回测',
  risk_filter: '只做风控过滤',
}

const RISK_LEVEL_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中等风险',
  high: '高风险',
  extreme: '极高风险',
}

const MARKET_REGIME_LABELS: Record<string, string> = {
  trend: '趋势行情',
  range: '震荡行情',
  volatile: '剧烈波动',
  news_positive: '新闻偏正面',
  news_neutral: '新闻中性',
  news_negative: '新闻偏负面',
  ai_unavailable: 'AI模型通道不可用',
  ai_unavailable_news_positive: '模型通道不可用，新闻偏正面',
  ai_unavailable_news_neutral: '模型通道不可用，新闻中性',
  ai_unavailable_news_negative: '模型通道不可用，新闻偏负面',
  invalid_payload: '结构异常',
  not_configured: '暂未配置',
}

const EXCHANGE_LABELS: Record<string, string> = {
  binance: '币安',
  okx: 'OKX',
}

const PROVIDER_LABELS: Record<string, string> = {
  right_code: 'Right Code',
  openai_compatible: 'OpenAI 兼容',
  openai: 'OpenAI 官方',
  deepseek: 'DeepSeek 官方',
  dashscope: '通义千问',
  moonshot: 'Kimi（月之暗面）',
  zhipu: '智谱 GLM',
  glm: '智谱 GLM',
  minimax: 'MiniMax 官方',
  ollama: 'Ollama 本地',
  aihubmix: 'AIHubMix',
  openrouter: 'OpenRouter',
  siliconflow: '硅基流动',
  local_ai_mock: '本地模拟分析',
  proxy_b: '备用通道 B',
  proxy_c: '备用通道 C',
  feishu: '飞书',
  wecom: '企业微信',
  telegram: 'Telegram',
  email: '邮箱',
  slack: 'Slack',
  discord: 'Discord',
}

const STRATEGY_LABELS: Record<string, string> = {
  ma_cross: '均线交叉',
  'MA Cross': '均线交叉',
  rsi_mean_reversion: '超买超卖回归',
  'RSI Mean Reversion': '超买超卖回归',
  grid: '网格策略',
  'Grid Trading': '网格策略',
  breakout: '突破策略',
  Breakout: '突破策略',
  bollinger_bands: '布林带回归',
  'Bollinger Bands': '布林带回归',
  macd_trend: 'MACD 趋势',
  'MACD Trend': 'MACD 趋势',
  trend_pullback: '趋势回踩',
  'Trend Pullback': '趋势回踩',
  dca: '定投建仓',
  DCA: '定投建仓',
  funding_rate_guard: '资金费率过滤',
  'Funding Rate Guard': '资金费率过滤',
  ai_filter: '智能风险过滤',
  'AI Filter': '智能风险过滤',
  manual: '手动操作',
}

const MODULE_LABELS: Record<string, string> = {
  system: '系统',
  strategy: '策略',
  backtest: '回测',
  ai: 'AI分析',
  risk: '风控',
  trading: '交易',
  data: '数据',
  market: '行情',
  news: '新闻',
  api: '接口',
  api_error: '接口错误',
}

const FIELD_LABELS: Record<string, string> = {
  id: '标识',
  model: '模型',
  base_url: 'Base URL',
  api_format: '接口协议',
  default_model: '默认模型',
  requires_api_key: '需要 Key',
  api_key_configured: '接口密钥',
  priority: '优先级',
  enabled: '是否启用',
  public_market_data: '公共行情数据',
  spot_trading_enabled: '现货交易',
  sandbox: '沙盒环境',
  withdraw_permission: '提现权限',
  mysql_host: 'MySQL 地址',
  repository_backend: '数据存储方式',
  default_exchange: '默认交易所',
  default_symbol: '默认币种',
  default_timeframe: '默认周期',
  public_exchange_data: '公共交易所行情',
  news_sentiment: '新闻情绪',
  news_feed_count: '新闻源数量',
  news_cache_ttl_seconds: '新闻缓存时间',
  max_data_latency_seconds: '最大数据延迟',
  feishu_webhook: '飞书通知',
  wecom_webhook: '企业微信通知',
  telegram_bot: 'Telegram 通知',
  email_smtp: '邮箱通知',
  slack_webhook: 'Slack 通知',
  discord_webhook: 'Discord 通知',
  severity: '提醒级别',
  fast_window: '快线周期',
  slow_window: '慢线周期',
  max_position_percent: '最大仓位占比',
  stop_loss_percent: '止损比例',
  take_profit_percent: '止盈比例',
  period: '周期',
  buy_below: '低于该值买入',
  sell_above: '高于该值卖出',
  lower_price: '网格下边界',
  upper_price: '网格上边界',
  grid_count: '网格数量',
  order_size_percent: '单格资金占比',
  spot_only: '只允许现货',
  lookback: '回看周期',
  volume_multiplier: '成交量放大倍数',
  deviation_multiplier: '标准差倍数',
  exit_on_middle: '中轨止盈',
  signal_window: '信号线周期',
  short_window: '短均线周期',
  long_window: '长均线周期',
  interval_candles: '定投间隔K线',
  max_funding_rate_percent: '最高资金费率',
  premium_threshold_percent: '合约溢价阈值',
  lookback_hours: '回看小时数',
  provider: '服务商',
  requires_json_schema: '要求结构化内容',
  cannot_place_orders: '不能直接下单',
  market_regime: '市场状态',
  sentiment_score: '情绪分',
  risk_level: '风险等级',
  event_risk: '重大事件风险',
  allowed_direction: '允许方向',
  confidence: '置信度',
  news: '新闻',
  status: '状态',
  article_count: '新闻数量',
  source_count: '来源数量',
  top_headlines: '主要标题',
}

const DATA_INTEGRITY_LABELS: Record<string, string> = {
  live_public: '实时公共行情',
  local_cache: '本地缓存行情',
  local_cache_empty: '本地缓存为空',
  empty: '暂无行情数据',
  exchange_error_cooling_down: '交易所异常，稍后重试',
  unknown: '数据状态未知',
}

const STRATEGY_FAMILY_LABELS: Record<string, string> = {
  trend_following: '趋势跟随',
  mean_reversion: '均值回归',
  range: '震荡网格',
  risk_filter: '风险过滤',
  position_building: '分批建仓',
  custom: '自定义',
}

const TIMEFRAME_LABELS: Record<string, string> = {
  '1m': '1 分钟',
  '5m': '5 分钟',
  '15m': '15 分钟',
  '1h': '1 小时',
  '4h': '4 小时',
  '1d': '1 天',
}

const TEXT_LABELS: Record<string, string> = {
  'from portfolio repository': '来自资产记录',
  'no realized PnL source': '暂无已实现盈亏来源',
  'no equity history': '暂无权益历史',
  'spot positions': '当前现货持仓',
  'public spot market data enabled; private API not configured': '已启用公共现货行情，未配置私有接口',
  'spot API not configured': '未配置现货接口',
  'Historical candles already available in local market_candles': '这段历史行情本地已经有了',
  'Historical candles synced into local market_candles': '历史行情已同步到本地数据库',
  'Historical sync requires REPOSITORY_BACKEND=mysql': '同步历史行情需要先启用 MySQL 数据库',
  'Local historical market data unavailable. Run historical data sync for this symbol/timeframe/date range first.':
    '本地没有这段历史 K 线，请先同步历史数据。',
  'MA Cross requires positive fast_window < slow_window parameters':
    '均线交叉策略要求快线周期大于 0，并且小于慢线周期。',
  'Grid Trading completed with spot long-only fixed-lot rules':
    '网格策略回测完成，已按现货只做多固定份额规则执行。',
  'Breakout completed with spot long-only rules': '突破策略回测完成，已按现货只做多规则执行。',
  'Bollinger Bands completed with spot long-only rules':
    '布林带回归回测完成，已按现货只做多规则执行。',
  'MACD Trend completed with spot long-only rules': 'MACD 趋势回测完成，已按现货只做多规则执行。',
  'Trend Pullback completed with spot long-only rules':
    '趋势回踩回测完成，已按现货只做多规则执行。',
  'DCA completed with spot long-only fixed-interval rules':
    '定投建仓回测完成，已按固定间隔现货买入规则执行。',
  'Grid Trading requires at least 2 candles, got 0':
    '网格策略至少需要 2 根 K 线。',
  'Grid Trading requires at least 2 candles, got 1':
    '网格策略至少需要 2 根 K 线。',
  'No AI proxy or enriched market context is configured.': '未配置AI模型通道，也没有可用的增强行情上下文。',
  'News sentiment is disabled.': '新闻情绪已关闭。',
  'No news RSS feeds configured.': '还没有配置新闻 RSS 源。',
  'News sentiment context analyzed locally.': '已使用本地新闻情绪规则完成分析。',
  'AI structured JSON validation passed.': 'AI分析结构化结果校验通过。',
  'right code returned valid structured JSON.': 'Right Code 返回了可用的结构化结果。',
  'right_code returned valid structured JSON.': 'Right Code 返回了可用的结构化结果。',
  'openai_compatible returned valid structured JSON.': 'OpenAI 兼容通道返回了可用的结构化结果。',
  'openai returned valid structured JSON.': 'OpenAI 返回了可用的结构化结果。',
  'deepseek returned valid structured JSON.': 'DeepSeek 官方返回了可用的结构化结果。',
  'dashscope returned valid structured JSON.': '通义千问返回了可用的结构化结果。',
  'moonshot returned valid structured JSON.': 'Kimi 返回了可用的结构化结果。',
  'zhipu returned valid structured JSON.': '智谱 GLM 返回了可用的结构化结果。',
  'minimax returned valid structured JSON.': 'MiniMax 返回了可用的结构化结果。',
  'ollama returned valid structured JSON.': 'Ollama 本地模型返回了可用的结构化结果。',
  'notification sent': '通知已发送',
  'FEISHU_WEBHOOK_URL is not configured': '还没有配置飞书通知地址',
  'WECOM_WEBHOOK_URL is not configured': '还没有配置企业微信通知地址',
  'TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID is not configured': '还没有配置 Telegram Bot Token 和 Chat ID',
  'EMAIL_SMTP_HOST and EMAIL_FROM and EMAIL_TO is not configured': '还没有配置邮箱 SMTP、发件人和收件人',
  'EMAIL_SMTP_HOST is not configured': '还没有配置邮箱 SMTP 地址',
  'EMAIL_FROM is not configured': '还没有配置邮箱发件人',
  'EMAIL_TO is not configured': '还没有配置邮箱收件人',
  'SLACK_WEBHOOK_URL is not configured': '还没有配置 Slack 通知地址',
  'DISCORD_WEBHOOK_URL is not configured': '还没有配置 Discord 通知地址',
  'end_date must be after start_date': '结束日期必须晚于开始日期',
  'MA Cross completed with spot long-only rules': '均线交叉回测完成，已按现货只做多规则执行。',
  'Kill Switch 已触发，禁止新开仓并要求撤销挂单。':
    'Kill Switch 已触发，禁止新开仓并要求撤销挂单。',
  '系统已暂停策略开仓，仅允许管理已有现货仓位。':
    '系统已暂停策略开仓，仅允许管理已有现货仓位。',
  '未配置账户余额来源，默认暂停新开仓。': '未配置账户余额来源，默认暂停新开仓。',
  '行情数据延迟或不可用，禁止新开仓。': '行情数据延迟或不可用，禁止新开仓。',
  '单笔浮动亏损超过阈值，要求减仓或人工检查。':
    '单笔浮动亏损超过阈值，要求减仓或人工检查。',
  '账户当日亏损代理指标超过阈值，禁止新开仓。':
    '账户当日亏损代理指标超过阈值，禁止新开仓。',
  '缺少权益曲线来源，暂不触发自动拦截。': '缺少权益曲线来源，暂不触发自动拦截。',
  '单币现货仓位超过阈值，要求降低该币种风险暴露。':
    '单币现货仓位超过阈值，要求降低该币种风险暴露。',
  '总现货仓位超过阈值，禁止新开仓。': '总现货仓位超过阈值，禁止新开仓。',
  '连续亏损或连续拒单达到阈值，暂停策略开仓。':
    '连续亏损或连续拒单达到阈值，暂停策略开仓。',
  'AI 风险等级或允许方向禁止新开仓。': 'AI 风险等级或允许方向禁止新开仓。',
  '风控禁止新开仓：允许撤单、持有或卖出现有现货仓位。':
    '风控禁止新开仓：允许撤单、持有或卖出现有现货仓位。',
  '风控要求降低仓位：仅允许减仓、撤单和风险处置。':
    '风控要求降低仓位：仅允许减仓、撤单和风险处置。',
  'P0 风控检查通过，仅允许现货 dry-run 或已确认的 Spot Live 动作。':
    'P0 风控检查通过，仅允许现货 dry-run 或已确认的 Spot Live 动作。',
}

const LOOKUP_LABELS: Record<string, string> = {
  ...STATUS_LABELS,
  ...ACTION_LABELS,
  ...RISK_RULE_LABELS,
  ...TRADING_MODE_LABELS,
  ...RISK_LEVEL_LABELS,
  ...MARKET_REGIME_LABELS,
  ...EXCHANGE_LABELS,
  ...PROVIDER_LABELS,
  ...STRATEGY_LABELS,
  ...MODULE_LABELS,
  ...FIELD_LABELS,
  ...DATA_INTEGRITY_LABELS,
  ...STRATEGY_FAMILY_LABELS,
  ...TIMEFRAME_LABELS,
  ...TEXT_LABELS,
}

function localizeLabel(value: string) {
  return translateText(value)
}

export function formatStatus(value: string | null | undefined) {
  if (!value) {
    return '-'
  }

  if (STATUS_LABELS[value]) {
    return localizeLabel(STATUS_LABELS[value])
  }

  const [prefix, ...rest] = value.split(':')
  const detail = rest.join(':').trim()
  if (detail) {
    return currentLanguage.value === 'zh'
      ? `${STATUS_LABELS[prefix] ?? formatCodeValue(prefix)}：${formatCodeValue(detail)}`
      : `${STATUS_LABELS[prefix] ? localizeLabel(STATUS_LABELS[prefix]) : formatCodeValue(prefix)}: ${formatCodeValue(detail)}`
  }

  return LOOKUP_LABELS[value] ? localizeLabel(LOOKUP_LABELS[value]) : fallbackCode(value)
}

export function formatAction(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return ACTION_LABELS[value] ? localizeLabel(ACTION_LABELS[value]) : formatStatus(value)
}

export function formatTradingMode(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return TRADING_MODE_LABELS[value] ? localizeLabel(TRADING_MODE_LABELS[value]) : formatStatus(value)
}

export function formatRiskLevel(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return RISK_LEVEL_LABELS[value] ? localizeLabel(RISK_LEVEL_LABELS[value]) : formatStatus(value)
}

export function formatMarketRegime(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return MARKET_REGIME_LABELS[value] ? localizeLabel(MARKET_REGIME_LABELS[value]) : formatStatus(value)
}

export function formatExchange(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return EXCHANGE_LABELS[value] ? localizeLabel(EXCHANGE_LABELS[value]) : value.toUpperCase()
}

export function formatProvider(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return PROVIDER_LABELS[value] ? localizeLabel(PROVIDER_LABELS[value]) : value
}

export function formatStrategyName(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return STRATEGY_LABELS[value] ? localizeLabel(STRATEGY_LABELS[value]) : value
}

export function formatModule(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return MODULE_LABELS[value] ? localizeLabel(MODULE_LABELS[value]) : formatStatus(value)
}

export function formatFieldName(value: string | number) {
  const key = String(value)
  return FIELD_LABELS[key] ? localizeLabel(FIELD_LABELS[key]) : formatStatus(key)
}

export function formatTimeframe(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  return TIMEFRAME_LABELS[value] ? localizeLabel(TIMEFRAME_LABELS[value]) : value
}

export function formatBoolean(value: boolean | string | null | undefined) {
  if (value === true || value === 'true') {
    return translateText('是')
  }
  if (value === false || value === 'false') {
    return translateText('否')
  }
  return '-'
}

export function formatDataIntegrity(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  if (value.startsWith('exchange_error:')) {
    const detail = value.replace('exchange_error:', '').trim()
    return currentLanguage.value === 'zh'
      ? `交易所行情不可用：${detail}`
      : `Exchange market data unavailable: ${detail}`
  }
  return DATA_INTEGRITY_LABELS[value] ? localizeLabel(DATA_INTEGRITY_LABELS[value]) : formatStatus(value)
}

export function formatCodeValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'boolean') {
    return formatBoolean(value)
  }
  if (typeof value === 'number') {
    return String(value)
  }

  const text = String(value).trim()
  if (text === 'true' || text === 'false') {
    return formatBoolean(text)
  }
  if (LOOKUP_LABELS[text]) {
    return localizeLabel(LOOKUP_LABELS[text])
  }
  if (text.startsWith('risk:')) {
    return currentLanguage.value === 'zh'
      ? `风控：${formatStatus(text.slice('risk:'.length))}`
      : `Risk: ${formatStatus(text.slice('risk:'.length))}`
  }
  if (text.startsWith('ai:')) {
    return currentLanguage.value === 'zh'
      ? `AI分析：${formatRiskLevel(text.slice('ai:'.length))}`
      : `AI Analysis: ${formatRiskLevel(text.slice('ai:'.length))}`
  }
  if (text.startsWith('exchange_error:')) {
    return formatDataIntegrity(text)
  }
  return fallbackCode(text)
}

export function formatSettingValue(key: string | number, value: unknown) {
  const field = String(key)
  const text = value === null || value === undefined ? '' : String(value)

  if (
    field.includes('configured')
    || field.includes('webhook')
    || field === 'telegram_bot'
    || field === 'telegram_bot_token'
    || field === 'telegram_chat_id'
    || field === 'email_smtp'
    || field === 'email_smtp_host'
    || field === 'email_smtp_username'
    || field === 'email_smtp_password'
  ) {
    return localizeLabel(text === 'true' || value === true ? '已配置' : '未配置')
  }
  if (field.includes('permission')) {
    return text === 'disabled' ? localizeLabel('已关闭') : formatCodeValue(value)
  }
  if (field.includes('enabled') || field.includes('public_')) {
    return localizeLabel(text === 'true' || value === true ? '已开启' : '未开启')
  }
  if (field.includes('exchange')) {
    return formatExchange(text)
  }
  if (field.includes('timeframe')) {
    return formatTimeframe(text)
  }
  if (field === 'severity') {
    return text === 'warning+' ? localizeLabel('注意及以上') : formatStatus(text)
  }
  return formatCodeValue(value)
}

export function formatRuleText(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  if (value === 'N/A') {
    return localizeLabel('暂未接入')
  }
  if (value === 'true' || value === 'false') {
    return formatBoolean(value)
  }
  const balanceMatch = value.match(/^(\d+) balances$/)
  if (balanceMatch) {
    return translateText(`${balanceMatch[1]} 条余额记录`)
  }
  const latencyMatch = value.match(/^(\d+)s \/ (.+)$/)
  if (latencyMatch) {
    return currentLanguage.value === 'zh'
      ? `${latencyMatch[1]} 秒 / ${formatDataIntegrity(latencyMatch[2])}`
      : `${latencyMatch[1]}s / ${formatDataIntegrity(latencyMatch[2])}`
  }
  const latencyThresholdMatch = value.match(/^<= (\d+)s and complete$/)
  if (latencyThresholdMatch) {
    return translateText(`<= ${latencyThresholdMatch[1]} 秒且数据完整`)
  }
  if (value === 'below high') {
    return localizeLabel('低于高风险')
  }
  return formatCodeValue(value)
}

export function formatMessage(value: string | null | undefined) {
  if (!value) {
    return '-'
  }
  const text = value.trim()
  if (TEXT_LABELS[text]) {
    return localizeLabel(TEXT_LABELS[text])
  }

  const strategyUpdated = text.match(/^Strategy configuration updated: (.+)$/)
  if (strategyUpdated) {
    return translateText(`策略配置已更新：${formatStrategyName(strategyUpdated[1])}`)
  }

  const backtestFinished = text.match(/^Backtest finished with status=([^,]+), trades=(\d+)$/)
  if (backtestFinished) {
    return translateText(`回测完成：${formatStatus(backtestFinished[1])}，共 ${backtestFinished[2]} 笔交易`)
  }

  const systemControl = text.match(
    /^System control updated: paused=(true|false), kill_switch_armed=(true|false), reason=(.+)$/,
  )
  if (systemControl) {
    return translateText(`系统控制已更新：暂停=${formatBoolean(systemControl[1])}，紧急停止=${formatBoolean(systemControl[2])}，原因=${formatStatus(systemControl[3])}`)
  }

  const aiValidated = text.match(/^AI structured payload validated with risk_level=(.+)$/)
  if (aiValidated) {
    return translateText(`AI分析结构化结果校验通过，风险等级：${formatRiskLevel(aiValidated[1])}`)
  }

  const aiFallback = text.match(/^AI proxy unavailable, conservative fallback applied: (.+)$/)
  if (aiFallback) {
    return translateText(`AI模型通道不可用，已切换为本地保守拦截：${aiFallback[1]}`)
  }

  const newsContextIncluded = text.match(
    /^News sentiment context included (\d+) article\(s\) from (\d+) source\(s\)\.$/,
  )
  if (newsContextIncluded) {
    return translateText(`已纳入新闻情绪上下文：${newsContextIncluded[1]} 条新闻，${newsContextIncluded[2]} 个来源。`)
  }

  const newsSentiment = text.match(
    /^News sentiment (positive|neutral|negative): score=([^,]+), articles=(\d+), event_risk=(true|false)\.$/,
  )
  if (newsSentiment) {
    return translateText(`新闻情绪${formatStatus(newsSentiment[1])}：评分 ${newsSentiment[2]}，新闻 ${newsSentiment[3]} 条，事件风险 ${formatBoolean(newsSentiment[4])}。`)
  }

  const strategySignal = text.match(/^Strategy signal captured: action=([^,]+), quantity=(.+)$/)
  if (strategySignal) {
    return translateText(`策略信号已记录：${formatAction(strategySignal[1])}，数量 ${strategySignal[2]}`)
  }

  const aiSnapshot = text.match(
    /^AI filter snapshot captured: risk_level=([^,]+), allowed_direction=([^,]+), confidence=([^,]+), provider=([^,]+), model=(.+)$/,
  )
  if (aiSnapshot) {
    return translateText(`AI分析快照已记录：${formatRiskLevel(aiSnapshot[1])}，允许${formatAction(aiSnapshot[2])}，置信度 ${aiSnapshot[3]}，通道 ${formatProvider(aiSnapshot[4])}，模型 ${aiSnapshot[5]}`)
  }

  const dryRunOrder = text.match(/^Dry-run order validated: status=([^,]+), risk_events=(\d+)$/)
  if (dryRunOrder) {
    return translateText(`模拟订单校验完成：${formatStatus(dryRunOrder[1])}，风控事件 ${dryRunOrder[2]} 条`)
  }

  const dryRunSpotOrder = text.match(/^Dry-run spot order validation result: ([^;]+); risk_events=(\d+)$/)
  if (dryRunSpotOrder) {
    return translateText(`模拟现货订单校验完成：${formatStatus(dryRunSpotOrder[1])}，风控事件 ${dryRunSpotOrder[2]} 条`)
  }

  const liveBlocked = text.match(/^Live spot order blocked before exchange submit: ([^;]+); risk_events=(\d+)$/)
  if (liveBlocked) {
    return translateText(`实盘订单已在提交前拦截：${formatStatus(liveBlocked[1])}，风控事件 ${liveBlocked[2]} 条`)
  }

  const liveSubmitted = text.match(/^Live spot order submitted: exchange=([^,]+), order_id=([^,]+), status=(.+)$/)
  if (liveSubmitted) {
    return translateText(`实盘订单已提交：${formatExchange(liveSubmitted[1])} ${liveSubmitted[2]}，状态 ${formatStatus(liveSubmitted[3])}`)
  }

  const liveCanceled = text.match(/^Live spot order canceled: exchange=([^,]+), order_id=(.+)$/)
  if (liveCanceled) {
    return translateText(`实盘撤单已提交：${formatExchange(liveCanceled[1])} ${liveCanceled[2]}`)
  }

  const riskEvent = text.match(/^Risk event persisted: (.+) -> ([^:]+): (.+)$/)
  if (riskEvent) {
    return translateText(`风控事件已记录：${formatStatus(riskEvent[1])}，处理动作 ${formatStatus(riskEvent[2])}。${formatMessage(riskEvent[3])}`)
  }

  const notificationTest = text.match(/^([a-z_]+) notification test result: (.+)$/)
  if (notificationTest) {
    return translateText(`${formatProvider(notificationTest[1])}通知测试结果：${formatMessage(notificationTest[2])}`)
  }

  const dryRunRequest = text.match(/^Dry-run order request received: ([^ ]+) (.+)$/)
  if (dryRunRequest) {
    return translateText(`收到模拟订单请求：${formatAction(dryRunRequest[1])} ${dryRunRequest[2]}`)
  }

  const unsupportedStrategy = text.match(/^P0 backtesting only supports ma_cross, got (.+)$/)
  if (unsupportedStrategy) {
    return translateText(`当前回测只支持均线交叉策略，收到的是：${formatStrategyName(unsupportedStrategy[1])}`)
  }

  const strategyNotFound = text.match(/^Strategy not found: (.+)$/)
  if (strategyNotFound) {
    return translateText(`找不到策略：${formatStrategyName(strategyNotFound[1])}`)
  }

  const strategyDisabled = text.match(/^Strategy disabled: (.+)$/)
  if (strategyDisabled) {
    return translateText(`策略已停用：${formatStrategyName(strategyDisabled[1])}`)
  }

  const invalidRange = text.match(/^Invalid date range: (.+)$/)
  if (invalidRange) {
    return translateText(`日期范围无效：${invalidRange[1]}`)
  }

  const maCrossCandles = text.match(/^MA Cross requires at least (\d+) candles, got (\d+)$/)
  if (maCrossCandles) {
    return translateText(`均线交叉策略至少需要 ${maCrossCandles[1]} 根 K 线，当前只有 ${maCrossCandles[2]} 根。`)
  }

  return replaceTechnicalTerms(formatCodeValue(text))
}

export function localizeJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => localizeJsonValue(item))
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [formatFieldName(key), localizeJsonValue(item)]),
    )
  }
  return formatCodeValue(value)
}

function fallbackCode(value: string) {
  return translateText(replaceTechnicalTerms(value))
}

function replaceTechnicalTerms(value: string) {
  if (currentLanguage.value === 'en') {
    return value
  }

  return value
    .replaceAll('Spot Live', '现货实盘')
    .replaceAll('Spot Dry-run', '现货模拟')
    .replaceAll('dry-run', '模拟运行')
    .replaceAll('Dry-run', '模拟运行')
    .replaceAll('Spot', '现货')
    .replaceAll('Live', '实盘')
    .replaceAll('Kill Switch', '紧急停止')
    .replaceAll('API', '接口')
    .replace(/\bAI\b(?!分析)/g, 'AI分析')
    .replaceAll('JSON', '结构化内容')
}
