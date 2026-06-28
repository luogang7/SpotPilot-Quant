<script setup lang="ts">
import {
  Bell,
  Bot,
  CalendarClock,
  Database,
  Eye,
  EyeOff,
  KeyRound,
  Save,
  Send,
  Settings2,
  ShieldCheck,
  WalletCards,
} from 'lucide-vue-next'
import { computed, ref, watch, type Component } from 'vue'

import { api } from '../../shared/api/client'
import {
  formatCodeValue,
  formatExchange,
  formatFieldName,
  formatMessage,
  formatProvider,
  formatSettingValue,
  formatStatus,
} from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MarketSymbolManager from '../../shared/components/MarketSymbolManager.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import type {
  AiProxySettingsUpdate,
  AiProxyConnectionTestResult,
  DailyPushResult,
  ExchangeAccountConnectionTestResult,
  ExchangeAccountSettingsUpdate,
  NotificationChannelSettingsUpdate,
  NotificationProvider,
  NotificationResult,
} from '../../shared/types/workbench'

type SettingsCategoryId = 'basic' | 'accounts' | 'ai' | 'data' | 'notifications' | 'safety'
type CategoryTone = 'success' | 'warning'

interface SettingsCategory {
  id: SettingsCategoryId
  title: string
  description: string
  summary: string
  count: number
  readyLabel: string
  tone: CategoryTone
  icon: Component
}

const basicDataKeys = ['default_exchange', 'default_symbol', 'default_timeframe']
const dataSourceKeys = [
  'mysql_host',
  'repository_backend',
  'public_exchange_data',
  'news_sentiment',
  'news_feed_count',
  'news_cache_ttl_seconds',
  'max_data_latency_seconds',
]

type AiProxyDraft = AiProxySettingsUpdate & {
  api_key_configured: boolean
  requires_api_key: boolean
}

type AiConnectionTestStatus = 'idle' | 'testing' | 'success' | 'error'

interface AiConnectionTestState {
  status: AiConnectionTestStatus
  result?: AiProxyConnectionTestResult
  message?: string
}

type ExchangeConnectionTestStatus = 'idle' | 'testing' | 'success' | 'error'

interface ExchangeConnectionTestState {
  status: ExchangeConnectionTestStatus
  result?: ExchangeAccountConnectionTestResult
  message?: string
}

type ExchangeAccountDraft = ExchangeAccountSettingsUpdate & {
  api_key_configured: boolean
  api_secret_configured: boolean
  passphrase_configured: boolean
  requires_passphrase: boolean
}

interface NotificationChannel {
  provider: NotificationProvider
  statusKey: string
  title: string
  description: string
  required: string
  kind: 'webhook' | 'telegram' | 'email'
  webhookLabel?: string
}

const notificationChannels: NotificationChannel[] = [
  {
    provider: 'wecom',
    statusKey: 'wecom_webhook',
    title: '企业微信',
    description: '企业微信群机器人 Webhook，适合内部告警群。',
    required: 'WECOM_WEBHOOK_URL',
    kind: 'webhook',
    webhookLabel: '企业微信群机器人 Webhook',
  },
  {
    provider: 'telegram',
    statusKey: 'telegram_bot',
    title: 'Telegram',
    description: '通过 Bot API 向指定 chat_id 发送消息。',
    required: 'TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID',
    kind: 'telegram',
  },
  {
    provider: 'email',
    statusKey: 'email_smtp',
    title: '邮箱',
    description: '使用 SMTP 向指定收件人发送测试邮件。',
    required: 'EMAIL_SMTP_HOST / EMAIL_FROM / EMAIL_TO',
    kind: 'email',
  },
  {
    provider: 'slack',
    statusKey: 'slack_webhook',
    title: 'Slack',
    description: 'Slack Incoming Webhook，用于频道告警。',
    required: 'SLACK_WEBHOOK_URL',
    kind: 'webhook',
    webhookLabel: 'Slack Incoming Webhook',
  },
  {
    provider: 'discord',
    statusKey: 'discord_webhook',
    title: 'Discord',
    description: 'Discord Webhook，用于频道或服务器通知。',
    required: 'DISCORD_WEBHOOK_URL',
    kind: 'webhook',
    webhookLabel: 'Discord Webhook',
  },
  {
    provider: 'feishu',
    statusKey: 'feishu_webhook',
    title: '飞书',
    description: '保留原飞书群机器人 Webhook 通道。',
    required: 'FEISHU_WEBHOOK_URL',
    kind: 'webhook',
    webhookLabel: '飞书群机器人 Webhook',
  },
]

interface NotificationDraft {
  provider: NotificationProvider
  webhook_url: string | null
  webhook_configured: boolean
  telegram_bot_token: string | null
  telegram_bot_token_configured: boolean
  telegram_chat_id: string | null
  telegram_chat_id_configured: boolean
  email_smtp_host: string | null
  email_smtp_host_configured: boolean
  email_smtp_port: number
  email_smtp_username: string | null
  email_smtp_username_configured: boolean
  email_smtp_password: string | null
  email_smtp_password_configured: boolean
  email_from: string | null
  email_from_configured: boolean
  email_to: string | null
  email_to_configured: boolean
  email_use_tls: boolean
}

type NotificationTestStatus = 'idle' | 'testing' | 'success' | 'error'

interface NotificationTestState {
  status: NotificationTestStatus
  result?: NotificationResult
  message?: string
}

interface DailyPushDraft {
  enabled: boolean
  schedule_time: string
  schedule_times: string
  run_immediately: boolean
}

type DailyPushActionStatus = 'idle' | 'saving' | 'running' | 'success' | 'error'

const { data, loading, error, refresh } = useResource(api.getSettingsSummary)
const activeCategory = ref<SettingsCategoryId>('basic')
const notificationTitle = ref('DSA 通知测试')
const notificationMessage = ref('SpotPilot Quant 现货量化领航台通知测试')
const notificationTimeoutSeconds = ref(20)
const notificationDrafts = ref<NotificationDraft[]>([])
const notificationSaving = ref(false)
const notificationSaveMessage = ref('')
const notificationSaveError = ref('')
const notificationTests = ref<Record<string, NotificationTestState>>({})
const visibleNotificationSecretFields = ref<Set<string>>(new Set())
const dailyPushDraft = ref<DailyPushDraft>({
  enabled: false,
  schedule_time: '18:00',
  schedule_times: '',
  run_immediately: false,
})
const dailyPushStatus = ref<DailyPushActionStatus>('idle')
const dailyPushMessage = ref('')
const dailyPushResult = ref<DailyPushResult | null>(null)
const aiProxyDrafts = ref<AiProxyDraft[]>([])
const aiSaving = ref(false)
const aiSaveMessage = ref('')
const aiSaveError = ref('')
const aiConnectionTests = ref<Record<string, AiConnectionTestState>>({})
const visibleApiKeySlots = ref<Set<string>>(new Set())
const exchangeAccountDrafts = ref<ExchangeAccountDraft[]>([])
const exchangeAccountSaving = ref(false)
const exchangeAccountSaveMessage = ref('')
const exchangeAccountSaveError = ref('')
const exchangeConnectionTests = ref<Record<string, ExchangeConnectionTestState>>({})
const visibleExchangeSecretFields = ref<Set<string>>(new Set())

const basicItems = computed(() => buildSettingItems(basicDataKeys))
const dataSourceItems = computed(() => buildSettingItems(dataSourceKeys))
const notificationItems = computed(() => {
  if (!data.value || !notificationDrafts.value.length) {
    return []
  }
  return notificationChannels.map((channel) => {
    const draft = getNotificationDraft(channel.provider)
    const configured = isNotificationDraftConfigured(draft, channel)
    return {
      ...channel,
      draft,
      configured,
      statusLabel: configured ? '已配置' : '待配置',
    }
  })
})

const providerTemplateById = computed(() => {
  const entries = data.value?.ai_provider_templates ?? []
  return new Map(entries.map((template) => [String(template.id), template]))
})

const settingsCategories = computed<SettingsCategory[]>(() => {
  if (!data.value) {
    return []
  }

  const configuredExchangeCount = data.value.exchanges.filter((exchange) =>
    isTruthySetting(exchange.api_key_configured),
  ).length
  const enabledExchangeCount = data.value.exchanges.filter((exchange) =>
    isTruthySetting(exchange.spot_trading_enabled),
  ).length
  const enabledAiCount = data.value.ai_proxies.filter((proxy) => isTruthySetting(proxy.enabled)).length
  const dataReadyCount = dataSourceKeys.filter((key) => hasUsefulValue(data.value?.data[key])).length
  const configuredNotificationCount = countConfiguredNotificationChannels(data.value.notifications)
  const safetyReadyCount = data.value.safety_checks.filter((item) =>
    isPassingSafetyStatus(item.status),
  ).length

  return [
    {
      id: 'basic',
      title: '基础设置',
      description: '交易所接口、默认标的和运行周期。',
      summary: '确认默认交易上下文与现货接口权限，后续行情、策略和交易动作都会沿用这些基础参数。',
      count: data.value.exchanges.length + basicDataKeys.length,
      readyLabel: `${configuredExchangeCount}/${data.value.exchanges.length} 接口`,
      tone: configuredExchangeCount > 0 ? 'success' : 'warning',
      icon: Settings2,
    },
    {
      id: 'accounts',
      title: '账号绑定',
      description: '币安、OKX API Key 与现货权限。',
      summary: '绑定交易所私有 API，用于读取账户余额、持仓、挂单，并在安全闸门允许后发送现货下单或撤单请求。',
      count: data.value.exchanges.length,
      readyLabel: `${enabledExchangeCount}/${data.value.exchanges.length} 现货启用`,
      tone: configuredExchangeCount > 0 ? 'success' : 'warning',
      icon: WalletCards,
    },
    {
      id: 'ai',
      title: 'AI 模型',
      description: '多模型供应商、通道和优先级。',
      summary: '管理 OpenAI 兼容、DeepSeek、通义千问、Kimi、GLM、MiniMax、Ollama 等模型通道，并按优先级故障切换。',
      count: data.value.ai_proxies.length + data.value.ai_provider_templates.length,
      readyLabel: `${enabledAiCount}/${data.value.ai_proxies.length} 启用`,
      tone: enabledAiCount > 0 ? 'success' : 'warning',
      icon: Bot,
    },
    {
      id: 'data',
      title: '数据源',
      description: '行情、新闻、本地存储和延迟阈值。',
      summary: '汇总公共行情、本地仓储、新闻情绪和缓存配置，用来判断回测与实时分析的数据来源。',
      count: dataSourceKeys.length,
      readyLabel: `${dataReadyCount}/${dataSourceKeys.length} 有值`,
      tone: dataReadyCount === dataSourceKeys.length ? 'success' : 'warning',
      icon: Database,
    },
    {
      id: 'notifications',
      title: '通知渠道',
      description: '企业微信、TG、邮箱和 Webhook。',
      summary: '检查告警出口是否可用，并直接选择渠道发送一条测试消息验证链路。',
      count: notificationChannels.length,
      readyLabel: `${configuredNotificationCount}/${notificationChannels.length} 已配置`,
      tone: configuredNotificationCount > 0 ? 'success' : 'warning',
      icon: Bell,
    },
    {
      id: 'safety',
      title: '安全检查',
      description: '实盘前的权限与熔断条件。',
      summary: '聚合现货边界、提现权限、实盘确认和紧急停止状态，作为上线前的最后检查。',
      count: data.value.safety_checks.length,
      readyLabel: `${safetyReadyCount}/${data.value.safety_checks.length} 通过`,
      tone: safetyReadyCount === data.value.safety_checks.length ? 'success' : 'warning',
      icon: ShieldCheck,
    },
  ]
})

const activeCategoryMeta = computed(() =>
  settingsCategories.value.find((category) => category.id === activeCategory.value),
)

const settingsOverview = computed(() => {
  if (!settingsCategories.value.length) {
    return { label: '等待设置摘要', tone: 'warning' as CategoryTone }
  }

  const readyCategoryCount = settingsCategories.value.filter((category) => category.tone === 'success').length
  return {
    label: `${readyCategoryCount}/${settingsCategories.value.length} 类可用`,
    tone: readyCategoryCount === settingsCategories.value.length ? 'success' as const : 'warning' as const,
  }
})

function buildSettingItems(keys: string[]) {
  if (!data.value) {
    return []
  }
  return keys.map((key) => ({
    key,
    label: formatFieldName(key),
    value: formatSettingValue(key, data.value?.data[key]),
  }))
}

function isTruthySetting(value: unknown) {
  return value === true || value === 'true'
}

function hasUsefulValue(value: unknown) {
  return value !== null && value !== undefined && value !== ''
}

function isPassingSafetyStatus(value: unknown) {
  const status = String(value)
  return status === 'passed' || status === 'enabled'
}

function statusTone(value: unknown): CategoryTone {
  return isTruthySetting(value) ? 'success' : 'warning'
}

function countConfiguredNotificationChannels(notifications: Record<string, string | number | boolean>) {
  return notificationChannels.filter((channel) => isTruthySetting(notifications[channel.statusKey])).length
}

function notificationProviderLabel(provider: string) {
  return notificationChannels.find((channel) => channel.provider === provider)?.title ?? formatCodeValue(provider)
}

function hydrateNotificationDrafts() {
  if (!data.value) {
    notificationDrafts.value = []
    return
  }

  const notifications = data.value.notifications
  notificationDrafts.value = notificationChannels.map((channel) => ({
    provider: channel.provider,
    webhook_url: null,
    webhook_configured: isTruthySetting(notifications[channel.statusKey]),
    telegram_bot_token: null,
    telegram_bot_token_configured: isTruthySetting(notifications.telegram_bot_token),
    telegram_chat_id: null,
    telegram_chat_id_configured: isTruthySetting(notifications.telegram_chat_id),
    email_smtp_host: null,
    email_smtp_host_configured: isTruthySetting(notifications.email_smtp_host),
    email_smtp_port: Number(notifications.email_smtp_port ?? 587),
    email_smtp_username: null,
    email_smtp_username_configured: isTruthySetting(notifications.email_smtp_username),
    email_smtp_password: null,
    email_smtp_password_configured: isTruthySetting(notifications.email_smtp_password),
    email_from: null,
    email_from_configured: isTruthySetting(notifications.email_from),
    email_to: null,
    email_to_configured: isTruthySetting(notifications.email_to),
    email_use_tls: notifications.email_use_tls !== false && notifications.email_use_tls !== 'false',
  }))
}

watch(data, hydrateNotificationDrafts, { immediate: true })

function hydrateDailyPushDraft() {
  if (!data.value) {
    return
  }
  const settings = data.value.data
  const scheduleTime = String(settings.schedule_time || '18:00')
  const rawScheduleTimes = String(settings.schedule_times || '')
  dailyPushDraft.value = {
    enabled: isTruthySetting(settings.schedule_enabled),
    schedule_time: scheduleTime,
    schedule_times: rawScheduleTimes && rawScheduleTimes !== scheduleTime ? rawScheduleTimes : '',
    run_immediately: isTruthySetting(settings.schedule_run_immediately),
  }
}

watch(data, hydrateDailyPushDraft, { immediate: true })

function templateKeyLabel(template: Record<string, string | boolean>) {
  return isTruthySetting(template.requires_api_key) ? '需要 Key' : '本地免 Key'
}

function providerOptions() {
  return data.value?.ai_provider_templates ?? []
}

function hydrateAiProxyDrafts() {
  if (!data.value) {
    aiProxyDrafts.value = []
    return
  }

  aiProxyDrafts.value = data.value.ai_proxies.map((proxy, index) => ({
    slot: (['A', 'B', 'C'][index] ?? 'A') as 'A' | 'B' | 'C',
    provider: String(proxy.id ?? ''),
    base_url: String(proxy.base_url ?? ''),
    api_key: null,
    api_key_configured: isTruthySetting(proxy.api_key_configured),
    model: String(proxy.model ?? ''),
    priority: Number(proxy.priority ?? index + 1),
    enabled: isTruthySetting(proxy.enabled),
    api_format: String(proxy.api_format ?? 'chat_completions') === 'responses' ? 'responses' : 'chat_completions',
    requires_api_key: isTruthySetting(proxy.requires_api_key),
  }))
}

watch(data, hydrateAiProxyDrafts, { immediate: true })

function hydrateExchangeAccountDrafts() {
  if (!data.value) {
    exchangeAccountDrafts.value = []
    return
  }

  exchangeAccountDrafts.value = data.value.exchanges.map((exchange) => ({
    exchange: String(exchange.id) === 'okx' ? 'okx' : 'binance',
    api_key: null,
    api_secret: null,
    passphrase: null,
    spot_trading_enabled: isTruthySetting(exchange.spot_trading_enabled),
    sandbox: isTruthySetting(exchange.sandbox),
    api_key_configured: isTruthySetting(exchange.api_key_value_configured ?? exchange.api_key_configured),
    api_secret_configured: isTruthySetting(exchange.api_secret_configured ?? exchange.api_key_configured),
    passphrase_configured: isTruthySetting(exchange.api_passphrase_configured),
    requires_passphrase: isTruthySetting(exchange.requires_passphrase),
  }))
}

watch(data, hydrateExchangeAccountDrafts, { immediate: true })

function applyProviderTemplate(draft: AiProxyDraft) {
  const template = providerTemplateById.value.get(draft.provider)
  if (!template) {
    return
  }
  draft.base_url = String(template.base_url ?? '')
  draft.model = String(template.default_model ?? draft.model)
  draft.api_format = String(template.api_format ?? 'chat_completions') === 'responses' ? 'responses' : 'chat_completions'
  draft.requires_api_key = isTruthySetting(template.requires_api_key)
}

function handleProviderChange(draft: AiProxyDraft) {
  applyProviderTemplate(draft)
  draft.api_key = ''
  draft.api_key_configured = false
  if (!draft.requires_api_key) {
    draft.api_key = ''
  }
}

function toggleApiKeyVisibility(slot: string) {
  const next = new Set(visibleApiKeySlots.value)
  if (next.has(slot)) {
    next.delete(slot)
  } else {
    next.add(slot)
  }
  visibleApiKeySlots.value = next
}

function apiKeyInputType(slot: string) {
  return visibleApiKeySlots.value.has(slot) ? 'text' : 'password'
}

function toggleExchangeSecretVisibility(fieldKey: string) {
  const next = new Set(visibleExchangeSecretFields.value)
  if (next.has(fieldKey)) {
    next.delete(fieldKey)
  } else {
    next.add(fieldKey)
  }
  visibleExchangeSecretFields.value = next
}

function exchangeSecretInputType(fieldKey: string) {
  return visibleExchangeSecretFields.value.has(fieldKey) ? 'text' : 'password'
}

function exchangeSecretPlaceholder(configured: boolean, label: string) {
  return configured ? `已配置，留空则保留现有 ${label}` : `填写 ${label}`
}

function apiKeyPlaceholder(draft: AiProxyDraft) {
  if (!draft.requires_api_key) {
    return '本地 Ollama 可留空'
  }
  return draft.api_key_configured ? '已配置，留空则保留现有 Key' : '填写 API Key'
}

function aiConnectionTestState(slot: string): AiConnectionTestState {
  return aiConnectionTests.value[slot] ?? { status: 'idle' }
}

function aiConnectionTestTone(state: AiConnectionTestState): CategoryTone {
  return state.status === 'success' ? 'success' : 'warning'
}

function aiConnectionTestLabel(state: AiConnectionTestState) {
  if (state.status === 'testing') {
    return '测试中'
  }
  if (state.status === 'success') {
    return '连通正常'
  }
  if (state.status === 'error') {
    return '连通失败'
  }
  return '未测试'
}

function aiConnectionTestMessage(slot: string) {
  const state = aiConnectionTestState(slot)
  if (state.result) {
    const suffix = state.result.used_saved_api_key ? '，使用已保存 Key' : ''
    return `${state.result.message} · ${state.result.latency_ms} ms${suffix}`
  }
  return state.message || '保存前可先测试当前服务商、Base URL、API Key、模型和接口协议是否可用。'
}

function setAiConnectionTest(slot: string, state: AiConnectionTestState) {
  aiConnectionTests.value = {
    ...aiConnectionTests.value,
    [slot]: state,
  }
}

function validateAiProxyDraftForTest(draft: AiProxyDraft) {
  if (!draft.provider.trim()) {
    return '请选择服务商'
  }
  if (!draft.base_url.trim()) {
    return '请填写 Base URL'
  }
  if (!draft.model.trim()) {
    return '请填写模型 ID'
  }
  if (draft.requires_api_key && !draft.api_key?.trim() && !draft.api_key_configured) {
    return '该服务商需要 API Key'
  }
  return ''
}

async function testAiProxyConnection(draft: AiProxyDraft) {
  const validationError = validateAiProxyDraftForTest(draft)
  if (validationError) {
    setAiConnectionTest(draft.slot, { status: 'error', message: validationError })
    return
  }

  setAiConnectionTest(draft.slot, { status: 'testing', message: '正在测试模型连通性' })
  try {
    const result = await api.testAiProxyConnection({
      proxy: {
        slot: draft.slot,
        provider: draft.provider,
        base_url: draft.base_url,
        api_key: draft.api_key && draft.api_key.trim() ? draft.api_key : null,
        model: draft.model,
        priority: draft.priority,
        enabled: draft.enabled,
        api_format: draft.api_format,
      },
      timeout_seconds: 12,
    })
    setAiConnectionTest(draft.slot, {
      status: result.success ? 'success' : 'error',
      result,
      message: result.message,
    })
  } catch (err) {
    setAiConnectionTest(draft.slot, {
      status: 'error',
      message: err instanceof Error ? err.message : '模型连通性测试失败',
    })
  }
}

function configuredCountText() {
  const enabled = aiProxyDrafts.value.filter((proxy) => proxy.enabled).length
  return `${enabled}/${aiProxyDrafts.value.length} 已启用`
}

function exchangeAccountConfiguredCountText() {
  const configured = exchangeAccountDrafts.value.filter((account) => isExchangeAccountCredentialReady(account)).length
  return `${configured}/${exchangeAccountDrafts.value.length} 已绑定`
}

function isExchangeAccountCredentialReady(account: ExchangeAccountDraft) {
  const baseReady = Boolean(account.api_key?.trim() || account.api_key_configured)
    && Boolean(account.api_secret?.trim() || account.api_secret_configured)
  if (!account.requires_passphrase) {
    return baseReady
  }
  return baseReady && Boolean(account.passphrase?.trim() || account.passphrase_configured)
}

function exchangeAccountTone(account: ExchangeAccountDraft): CategoryTone {
  return isExchangeAccountCredentialReady(account) ? 'success' : 'warning'
}

function exchangeAccountReadyLabel(account: ExchangeAccountDraft) {
  return isExchangeAccountCredentialReady(account) ? '凭证已配置' : '待配置凭证'
}

function exchangeFieldKey(account: ExchangeAccountDraft, field: string) {
  return `${account.exchange}:${field}`
}

function exchangeConnectionTestState(exchange: string): ExchangeConnectionTestState {
  return exchangeConnectionTests.value[exchange] ?? { status: 'idle' }
}

function exchangeConnectionTestTone(state: ExchangeConnectionTestState): CategoryTone {
  return state.status === 'success' ? 'success' : 'warning'
}

function exchangeConnectionTestLabel(state: ExchangeConnectionTestState) {
  if (state.status === 'testing') {
    return '测试中'
  }
  if (state.status === 'success') {
    return '连通正常'
  }
  if (state.status === 'error') {
    return '连通失败'
  }
  return '未测试'
}

function exchangeConnectionTestMessage(account: ExchangeAccountDraft) {
  const state = exchangeConnectionTestState(account.exchange)
  if (state.result) {
    const savedSuffix = state.result.used_saved_credentials ? '，使用已保存凭证' : ''
    return `${state.result.message} · ${state.result.latency_ms} ms · ${state.result.balance_asset_count} 个资产${savedSuffix}`
  }
  return state.message || '保存前可先测试当前 API Key、Secret、Passphrase、沙盒环境和只读余额权限是否可用。'
}

function setExchangeConnectionTest(exchange: string, state: ExchangeConnectionTestState) {
  exchangeConnectionTests.value = {
    ...exchangeConnectionTests.value,
    [exchange]: state,
  }
}

function credentialPayload(value: string | null | undefined, configured: boolean) {
  if (value === null || value === undefined) {
    return configured ? null : ''
  }
  if (value.trim()) {
    return value.trim()
  }
  return configured ? null : ''
}

function notificationChannel(provider: NotificationProvider) {
  return notificationChannels.find((channel) => channel.provider === provider) ?? notificationChannels[0]
}

function defaultNotificationDraft(provider: NotificationProvider): NotificationDraft {
  return {
    provider,
    webhook_url: null,
    webhook_configured: false,
    telegram_bot_token: null,
    telegram_bot_token_configured: false,
    telegram_chat_id: null,
    telegram_chat_id_configured: false,
    email_smtp_host: null,
    email_smtp_host_configured: false,
    email_smtp_port: 587,
    email_smtp_username: null,
    email_smtp_username_configured: false,
    email_smtp_password: null,
    email_smtp_password_configured: false,
    email_from: null,
    email_from_configured: false,
    email_to: null,
    email_to_configured: false,
    email_use_tls: true,
  }
}

function getNotificationDraft(provider: NotificationProvider) {
  return notificationDrafts.value.find((draft) => draft.provider === provider) ?? defaultNotificationDraft(provider)
}

function notificationFieldKey(provider: NotificationProvider, field: string) {
  return `${provider}:${field}`
}

function toggleNotificationSecretVisibility(fieldKey: string) {
  const next = new Set(visibleNotificationSecretFields.value)
  if (next.has(fieldKey)) {
    next.delete(fieldKey)
  } else {
    next.add(fieldKey)
  }
  visibleNotificationSecretFields.value = next
}

function notificationSecretInputType(fieldKey: string) {
  return visibleNotificationSecretFields.value.has(fieldKey) ? 'text' : 'password'
}

function notificationSecretPlaceholder(configured: boolean, label: string) {
  return configured ? `已配置，留空则保留现有 ${label}` : `填写 ${label}`
}

function isNotificationDraftConfigured(draft: NotificationDraft, channel = notificationChannel(draft.provider)) {
  if (channel.kind === 'webhook') {
    return Boolean(draft.webhook_url?.trim() || draft.webhook_configured)
  }
  if (channel.kind === 'telegram') {
    return Boolean(
      (draft.telegram_bot_token?.trim() || draft.telegram_bot_token_configured)
        && (draft.telegram_chat_id?.trim() || draft.telegram_chat_id_configured),
    )
  }
  return Boolean(
    (draft.email_smtp_host?.trim() || draft.email_smtp_host_configured)
      && (draft.email_from?.trim() || draft.email_from_configured)
      && (draft.email_to?.trim() || draft.email_to_configured),
  )
}

function notificationReadyLabel(draft: NotificationDraft, channel = notificationChannel(draft.provider)) {
  if (channel.kind === 'telegram') {
    const readyCount = [
      draft.telegram_bot_token?.trim() || draft.telegram_bot_token_configured,
      draft.telegram_chat_id?.trim() || draft.telegram_chat_id_configured,
    ].filter(Boolean).length
    return `${readyCount}/2 已配置`
  }
  if (channel.kind === 'email') {
    const readyCount = [
      draft.email_smtp_host?.trim() || draft.email_smtp_host_configured,
      draft.email_from?.trim() || draft.email_from_configured,
      draft.email_to?.trim() || draft.email_to_configured,
    ].filter(Boolean).length
    return `${readyCount}/3 必填`
  }
  return isNotificationDraftConfigured(draft, channel) ? '已配置' : '待配置'
}

function notificationPayload(draft: NotificationDraft): NotificationChannelSettingsUpdate {
  const channel = notificationChannel(draft.provider)
  if (channel.kind === 'webhook') {
    return {
      provider: draft.provider,
      webhook_url: credentialPayload(draft.webhook_url, draft.webhook_configured),
    }
  }
  if (channel.kind === 'telegram') {
    return {
      provider: draft.provider,
      telegram_bot_token: credentialPayload(
        draft.telegram_bot_token,
        draft.telegram_bot_token_configured,
      ),
      telegram_chat_id: credentialPayload(draft.telegram_chat_id, draft.telegram_chat_id_configured),
    }
  }
  return {
    provider: draft.provider,
    email_smtp_host: credentialPayload(draft.email_smtp_host, draft.email_smtp_host_configured),
    email_smtp_port: draft.email_smtp_port,
    email_smtp_username: credentialPayload(
      draft.email_smtp_username,
      draft.email_smtp_username_configured,
    ),
    email_smtp_password: credentialPayload(
      draft.email_smtp_password,
      draft.email_smtp_password_configured,
    ),
    email_from: credentialPayload(draft.email_from, draft.email_from_configured),
    email_to: credentialPayload(draft.email_to, draft.email_to_configured),
    email_use_tls: draft.email_use_tls,
  }
}

function validateNotificationDraft(draft: NotificationDraft) {
  if (notificationChannel(draft.provider).kind === 'email') {
    if (!Number.isFinite(Number(draft.email_smtp_port)) || draft.email_smtp_port < 1 || draft.email_smtp_port > 65535) {
      return 'SMTP 端口需要在 1 到 65535 之间'
    }
  }
  return ''
}

function notificationTestState(provider: NotificationProvider): NotificationTestState {
  return notificationTests.value[provider] ?? { status: 'idle' }
}

function notificationTestTone(state: NotificationTestState): CategoryTone {
  return state.status === 'success' ? 'success' : 'warning'
}

function notificationTestLabel(state: NotificationTestState) {
  if (state.status === 'testing') {
    return '测试中'
  }
  if (state.status === 'success') {
    return '已发送'
  }
  if (state.status === 'error') {
    return '待检查'
  }
  return '未测试'
}

function notificationTestMessage(provider: NotificationProvider) {
  const state = notificationTestState(provider)
  if (state.result) {
    return `${notificationProviderLabel(state.result.provider)}：${formatMessage(state.result.message)}`
  }
  return state.message || `${notificationChannel(provider).required}`
}

function setNotificationTest(provider: NotificationProvider, state: NotificationTestState) {
  notificationTests.value = {
    ...notificationTests.value,
    [provider]: state,
  }
}

function validateDailyPushDraft() {
  const timePattern = /^(?:[01]\d|2[0-3]):[0-5]\d$/
  if (!timePattern.test(dailyPushDraft.value.schedule_time)) {
    return '默认推送时间需要使用 HH:MM 格式'
  }
  const invalidItems = dailyPushDraft.value.schedule_times
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item && !timePattern.test(item))
  if (invalidItems.length) {
    return `多时间点格式不正确：${invalidItems.join(', ')}`
  }
  return ''
}

function dailyPushConfiguredLabel() {
  if (!dailyPushDraft.value.enabled) {
    return '未启用'
  }
  const times = dailyPushDraft.value.schedule_times.trim() || dailyPushDraft.value.schedule_time
  return `已启用 ${times}`
}

function dailyPushTone(): CategoryTone {
  return dailyPushDraft.value.enabled ? 'success' : 'warning'
}

function dailyPushResultMessage() {
  if (dailyPushResult.value) {
    const channels = dailyPushResult.value.results
      .map((result) => `${notificationProviderLabel(result.provider)} ${result.success ? '成功' : '失败'}`)
      .join('，')
    return channels || dailyPushResult.value.title
  }
  return dailyPushMessage.value || '开启后调度器会按保存的时间自动生成并推送日报。'
}

async function saveDailyPushSettings(options: { silent?: boolean } = {}) {
  const validationError = validateDailyPushDraft()
  if (validationError) {
    dailyPushStatus.value = 'error'
    dailyPushMessage.value = validationError
    throw new Error(validationError)
  }
  dailyPushStatus.value = 'saving'
  dailyPushMessage.value = ''
  dailyPushResult.value = null
  try {
    const updated = await api.updateDailyPushSettings({
      enabled: dailyPushDraft.value.enabled,
      schedule_time: dailyPushDraft.value.schedule_time,
      schedule_times: dailyPushDraft.value.schedule_times.trim(),
      run_immediately: dailyPushDraft.value.run_immediately,
    })
    data.value = updated
    dailyPushStatus.value = 'success'
    dailyPushMessage.value = options.silent ? '' : '每日推送配置已保存'
    void refresh({ silent: true })
  } catch (err) {
    dailyPushStatus.value = 'error'
    dailyPushMessage.value = err instanceof Error ? err.message : '保存每日推送配置失败'
    throw err
  }
}

async function handleSaveDailyPushSettings() {
  try {
    await saveDailyPushSettings()
  } catch {
    // The visible status message is set by saveDailyPushSettings.
  }
}

async function runDailyPushNow() {
  dailyPushStatus.value = 'running'
  dailyPushMessage.value = '正在生成并发送每日量化日报'
  dailyPushResult.value = null
  try {
    await saveDailyPushSettings({ silent: true })
    dailyPushStatus.value = 'running'
    dailyPushMessage.value = '正在发送每日量化日报'
    const result = await api.runDailyPushNotification()
    dailyPushResult.value = result
    dailyPushStatus.value = result.success ? 'success' : 'error'
    dailyPushMessage.value = result.success ? '每日量化日报已发送' : '日报生成完成，但没有成功送达的渠道'
    void refresh({ silent: true })
  } catch (err) {
    dailyPushStatus.value = 'error'
    dailyPushMessage.value = err instanceof Error ? err.message : '立即推送失败'
  }
}

async function saveNotificationChannelSettings(draft: NotificationDraft) {
  const validationError = validateNotificationDraft(draft)
  if (validationError) {
    throw new Error(validationError)
  }
  const updated = await api.updateNotificationSettings({
    channels: [notificationPayload(draft)],
  })
  data.value = updated
  void refresh({ silent: true })
}

async function saveNotificationSettings() {
  notificationSaving.value = true
  notificationSaveMessage.value = ''
  notificationSaveError.value = ''
  try {
    for (const draft of notificationDrafts.value) {
      const validationError = validateNotificationDraft(draft)
      if (validationError) {
        throw new Error(validationError)
      }
    }
    const updated = await api.updateNotificationSettings({
      channels: notificationDrafts.value.map((draft) => notificationPayload(draft)),
    })
    data.value = updated
    notificationSaveMessage.value = '通知渠道配置已保存'
    void refresh({ silent: true })
  } catch (err) {
    notificationSaveError.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    notificationSaving.value = false
  }
}

async function testNotification(provider: NotificationProvider) {
  const draft = getNotificationDraft(provider)
  setNotificationTest(provider, { status: 'testing', message: '正在保存并发送测试通知' })
  try {
    await saveNotificationChannelSettings(draft)
    const result = await api.sendTestNotification({
      provider,
      title: notificationTitle.value,
      message: notificationMessage.value,
      timeout_seconds: notificationTimeoutSeconds.value,
    })
    setNotificationTest(provider, {
      status: result.success ? 'success' : 'error',
      result,
      message: result.message,
    })
  } catch (err) {
    setNotificationTest(provider, {
      status: 'error',
      message: err instanceof Error ? err.message : '通知测试失败',
    })
  }
}

function validateExchangeAccountDrafts() {
  for (const account of exchangeAccountDrafts.value) {
    if (!account.spot_trading_enabled) {
      continue
    }
    if (!isExchangeAccountCredentialReady(account)) {
      return `${formatExchange(account.exchange)} 开启现货交易前需要先配置完整 API Key`
    }
  }
  return ''
}

function exchangeAccountPayload(account: ExchangeAccountDraft): ExchangeAccountSettingsUpdate {
  return {
    exchange: account.exchange,
    api_key: credentialPayload(account.api_key, account.api_key_configured),
    api_secret: credentialPayload(account.api_secret, account.api_secret_configured),
    passphrase: account.requires_passphrase
      ? credentialPayload(account.passphrase, account.passphrase_configured)
      : null,
    spot_trading_enabled: account.spot_trading_enabled,
    sandbox: account.sandbox,
  }
}

function validateExchangeAccountDraftForTest(account: ExchangeAccountDraft) {
  if (!isExchangeAccountCredentialReady(account)) {
    return `${formatExchange(account.exchange)} 需要完整 API Key 后才能测试`
  }
  return ''
}

async function testExchangeAccountConnection(account: ExchangeAccountDraft) {
  const validationError = validateExchangeAccountDraftForTest(account)
  if (validationError) {
    setExchangeConnectionTest(account.exchange, { status: 'error', message: validationError })
    return
  }

  setExchangeConnectionTest(account.exchange, { status: 'testing', message: '正在测试交易所账号连通性' })
  try {
    const result = await api.testExchangeAccountConnection({
      account: exchangeAccountPayload(account),
      timeout_seconds: 12,
    })
    setExchangeConnectionTest(account.exchange, {
      status: result.success ? 'success' : 'error',
      result,
      message: result.message,
    })
  } catch (err) {
    setExchangeConnectionTest(account.exchange, {
      status: 'error',
      message: err instanceof Error ? err.message : '交易所账号连通性测试失败',
    })
  }
}

async function saveExchangeAccountSettings() {
  exchangeAccountSaveMessage.value = ''
  exchangeAccountSaveError.value = ''
  const validationError = validateExchangeAccountDrafts()
  if (validationError) {
    exchangeAccountSaveError.value = validationError
    return
  }

  exchangeAccountSaving.value = true
  try {
    const updated = await api.updateExchangeAccountSettings({
      accounts: exchangeAccountDrafts.value.map((account) => exchangeAccountPayload(account)),
    })
    data.value = updated
    exchangeAccountSaveMessage.value = '交易所账号绑定已保存'
    void refresh({ silent: true })
  } catch (err) {
    exchangeAccountSaveError.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    exchangeAccountSaving.value = false
  }
}

async function saveAiProxySettings() {
  aiSaving.value = true
  aiSaveMessage.value = ''
  aiSaveError.value = ''
  try {
    const updated = await api.updateAiProxySettings({
      proxies: aiProxyDrafts.value.map((draft) => ({
        slot: draft.slot,
        provider: draft.provider,
        base_url: draft.base_url,
        api_key:
          draft.api_key && draft.api_key.trim()
            ? draft.api_key
            : draft.api_key_configured && draft.requires_api_key
              ? null
              : '',
        model: draft.model,
        priority: draft.priority,
        enabled: draft.enabled,
        api_format: draft.api_format,
      })),
    })
    data.value = updated
    aiSaveMessage.value = 'AI 模型配置已保存'
    void refresh({ silent: true })
  } catch (err) {
    aiSaveError.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    aiSaving.value = false
  }
}

function exchangeTone(exchange: Record<string, string | boolean>): CategoryTone {
  return isTruthySetting(exchange.api_key_configured) ? 'success' : 'warning'
}

function safetyTone(value: unknown): CategoryTone {
  return isPassingSafetyStatus(value) ? 'success' : 'warning'
}
</script>

<template>
  <div class="page">
    <header class="page-header settings-header">
      <div>
        <h1 class="page-title">项目设置</h1>
        <p class="page-subtitle">按配置分类管理交易所接口、AI 模型通道、数据源、通知和安全检查。</p>
      </div>
      <div class="page-actions">
        <StatusBadge v-if="data" :label="settingsOverview.label" :tone="settingsOverview.tone" />
      </div>
    </header>

    <EmptyState v-if="loading" state="loading" message="正在加载设置摘要" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <template v-else-if="data">
      <div class="settings-layout">
        <aside class="settings-category-panel" aria-label="配置分类">
          <div class="settings-category-panel__head">
            <strong>配置分类</strong>
            <span>按模块整理设置摘要。</span>
          </div>
          <button
            v-for="category in settingsCategories"
            :key="category.id"
            type="button"
            class="settings-category"
            :class="{ active: activeCategory === category.id }"
            @click="activeCategory = category.id"
          >
            <span class="settings-category__icon">
              <component :is="category.icon" :size="18" />
            </span>
            <span class="settings-category__copy">
              <strong>{{ category.title }}</strong>
              <small>{{ category.description }}</small>
            </span>
            <span class="settings-category__meta">
              <span class="settings-category__count">{{ category.count }}</span>
              <StatusBadge :label="category.readyLabel" :tone="category.tone" />
            </span>
          </button>
        </aside>

        <div class="settings-detail">
          <section class="settings-detail-hero">
            <div>
              <span class="settings-kicker">当前分类</span>
              <h2>{{ activeCategoryMeta?.title }}</h2>
              <p>{{ activeCategoryMeta?.summary }}</p>
            </div>
            <StatusBadge
              v-if="activeCategoryMeta"
              :label="activeCategoryMeta.readyLabel"
              :tone="activeCategoryMeta.tone"
            />
          </section>

          <section v-if="activeCategory === 'basic'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>默认交易上下文</h3>
                <p>影响行情加载、策略筛选和下单表单的默认范围。</p>
              </div>
            </div>
            <div class="settings-key-grid">
              <article v-for="item in basicItems" :key="item.key" class="settings-key-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </article>
            </div>

            <div class="settings-section__head">
              <div>
                <h3>自定义币种</h3>
                <p>添加后会出现在行情、AI 分析和回测的币种下拉框中。</p>
              </div>
            </div>
            <MarketSymbolManager />

            <div class="settings-section__head">
              <div>
                <h3>交易所接口</h3>
                <p>保留现货交易边界，提现权限必须关闭。</p>
              </div>
            </div>
            <div class="settings-card-grid">
              <article
                v-for="exchange in data.exchanges"
                :key="String(exchange.id)"
                class="settings-config-card"
                :class="exchangeTone(exchange)"
              >
                <header>
                  <h4>{{ formatExchange(String(exchange.id)) }}</h4>
                  <StatusBadge
                    :label="formatSettingValue('api_key_configured', exchange.api_key_configured)"
                    :tone="exchangeTone(exchange)"
                  />
                </header>
                <dl class="settings-pairs">
                  <div>
                    <dt>公共行情</dt>
                    <dd>{{ formatSettingValue('public_market_data', exchange.public_market_data) }}</dd>
                  </div>
                  <div>
                    <dt>现货交易</dt>
                    <dd>
                      <StatusBadge
                        :label="formatSettingValue('enabled', exchange.spot_trading_enabled)"
                        :tone="statusTone(exchange.spot_trading_enabled)"
                      />
                    </dd>
                  </div>
                  <div>
                    <dt>沙盒环境</dt>
                    <dd>{{ formatSettingValue('enabled', exchange.sandbox) }}</dd>
                  </div>
                  <div>
                    <dt>提现权限</dt>
                    <dd>
                      <StatusBadge
                        :label="formatSettingValue('withdraw_permission', exchange.withdraw_permission)"
                        tone="success"
                      />
                    </dd>
                  </div>
                </dl>
              </article>
            </div>
          </section>

          <section v-else-if="activeCategory === 'accounts'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>交易所账号绑定</h3>
                <p>保存私有 API 后，系统才能读取真实账户余额、持仓和未成交挂单。</p>
              </div>
              <StatusBadge
                :label="exchangeAccountConfiguredCountText()"
                :tone="exchangeAccountDrafts.some((account) => isExchangeAccountCredentialReady(account)) ? 'success' : 'warning'"
              />
            </div>

            <form class="settings-account-editor" @submit.prevent="saveExchangeAccountSettings">
              <div class="settings-ai-toolbar">
                <div>
                  <strong>账号列表</strong>
                  <span>密钥不会回显；留空保存会继续保留后端已有密钥。</span>
                </div>
                <div class="toolbar-row">
                  <span v-if="exchangeAccountSaveError" class="inline-status negative">
                    {{ exchangeAccountSaveError }}
                  </span>
                  <span v-else-if="exchangeAccountSaveMessage" class="inline-status">
                    {{ exchangeAccountSaveMessage }}
                  </span>
                  <button type="submit" class="primary-button" :disabled="exchangeAccountSaving">
                    {{ exchangeAccountSaving ? '保存中' : '保存账号绑定' }}
                  </button>
                </div>
              </div>

              <article
                v-for="account in exchangeAccountDrafts"
                :key="account.exchange"
                class="settings-account-card"
                :class="exchangeAccountTone(account)"
              >
                <header>
                  <div>
                    <h4>{{ formatExchange(account.exchange) }}</h4>
                    <span>
                      {{ account.requires_passphrase ? 'API Key / Secret / Passphrase' : 'API Key / Secret' }}
                    </span>
                  </div>
                  <div class="settings-ai-channel__status">
                    <StatusBadge
                      :label="exchangeAccountReadyLabel(account)"
                      :tone="exchangeAccountTone(account)"
                    />
                    <StatusBadge
                      :label="account.spot_trading_enabled ? '现货已启用' : '现货未启用'"
                      :tone="account.spot_trading_enabled ? 'success' : 'warning'"
                    />
                    <StatusBadge
                      :label="exchangeConnectionTestLabel(exchangeConnectionTestState(account.exchange))"
                      :tone="exchangeConnectionTestTone(exchangeConnectionTestState(account.exchange))"
                    />
                    <button
                      type="button"
                      class="compact-button"
                      :disabled="exchangeConnectionTestState(account.exchange).status === 'testing'"
                      @click="testExchangeAccountConnection(account)"
                    >
                      <Send :size="14" />
                      {{ exchangeConnectionTestState(account.exchange).status === 'testing' ? '测试中' : '测试连接' }}
                    </button>
                  </div>
                </header>

                <div class="settings-account-grid">
                  <div class="form-field">
                    <label>API Key</label>
                    <div class="settings-secret-input">
                      <KeyRound :size="15" />
                      <input
                        v-model="account.api_key"
                        :type="exchangeSecretInputType(exchangeFieldKey(account, 'api_key'))"
                        :placeholder="exchangeSecretPlaceholder(account.api_key_configured, 'API Key')"
                      />
                      <button
                        type="button"
                        class="compact-button icon-only-button"
                        :title="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_key')) ? '隐藏 API Key' : '显示 API Key'"
                        :aria-label="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_key')) ? '隐藏 API Key' : '显示 API Key'"
                        @click="toggleExchangeSecretVisibility(exchangeFieldKey(account, 'api_key'))"
                      >
                        <component
                          :is="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_key')) ? EyeOff : Eye"
                          :size="15"
                        />
                      </button>
                    </div>
                  </div>

                  <div class="form-field">
                    <label>API Secret</label>
                    <div class="settings-secret-input">
                      <KeyRound :size="15" />
                      <input
                        v-model="account.api_secret"
                        :type="exchangeSecretInputType(exchangeFieldKey(account, 'api_secret'))"
                        :placeholder="exchangeSecretPlaceholder(account.api_secret_configured, 'API Secret')"
                      />
                      <button
                        type="button"
                        class="compact-button icon-only-button"
                        :title="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_secret')) ? '隐藏 API Secret' : '显示 API Secret'"
                        :aria-label="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_secret')) ? '隐藏 API Secret' : '显示 API Secret'"
                        @click="toggleExchangeSecretVisibility(exchangeFieldKey(account, 'api_secret'))"
                      >
                        <component
                          :is="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'api_secret')) ? EyeOff : Eye"
                          :size="15"
                        />
                      </button>
                    </div>
                  </div>

                  <div v-if="account.requires_passphrase" class="form-field">
                    <label>Passphrase</label>
                    <div class="settings-secret-input">
                      <KeyRound :size="15" />
                      <input
                        v-model="account.passphrase"
                        :type="exchangeSecretInputType(exchangeFieldKey(account, 'passphrase'))"
                        :placeholder="exchangeSecretPlaceholder(account.passphrase_configured, 'Passphrase')"
                      />
                      <button
                        type="button"
                        class="compact-button icon-only-button"
                        :title="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'passphrase')) ? '隐藏 Passphrase' : '显示 Passphrase'"
                        :aria-label="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'passphrase')) ? '隐藏 Passphrase' : '显示 Passphrase'"
                        @click="toggleExchangeSecretVisibility(exchangeFieldKey(account, 'passphrase'))"
                      >
                        <component
                          :is="visibleExchangeSecretFields.has(exchangeFieldKey(account, 'passphrase')) ? EyeOff : Eye"
                          :size="15"
                        />
                      </button>
                    </div>
                  </div>

                  <label class="settings-toggle-option">
                    <input v-model="account.sandbox" type="checkbox" />
                    <span>
                      <strong>沙盒环境</strong>
                      <small>{{ account.sandbox ? '已开启' : '未开启' }}</small>
                    </span>
                  </label>

                  <label class="settings-toggle-option">
                    <input v-model="account.spot_trading_enabled" type="checkbox" />
                    <span>
                      <strong>现货交易接口</strong>
                      <small>{{ account.spot_trading_enabled ? '允许读取持仓与挂单操作' : '仅保存凭证，不启用私有交易' }}</small>
                    </span>
                  </label>
                </div>

                <dl class="settings-pairs">
                  <div>
                    <dt>余额与持仓读取</dt>
                    <dd>{{ isExchangeAccountCredentialReady(account) ? '可用' : '等待凭证' }}</dd>
                  </div>
                  <div>
                    <dt>挂单与撤单</dt>
                    <dd>{{ account.spot_trading_enabled ? '交易所接口已启用' : '交易所接口未启用' }}</dd>
                  </div>
                  <div>
                    <dt>提现权限</dt>
                    <dd>必须关闭</dd>
                  </div>
                  <div>
                    <dt>全局实盘闸门</dt>
                    <dd>{{ formatSettingValue('enabled', data.data.live_trading_enabled) }}</dd>
                  </div>
                </dl>

                <div
                  class="settings-account-test-message"
                  :class="exchangeConnectionTestState(account.exchange).status"
                >
                  {{ exchangeConnectionTestMessage(account) }}
                </div>
              </article>
            </form>
          </section>

          <section v-else-if="activeCategory === 'ai'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>AI 模型通道</h3>
                <p>选择服务商后自动带出协议、Base URL 和模型示例，再填 API Key 保存。</p>
              </div>
              <StatusBadge :label="configuredCountText()" :tone="aiProxyDrafts.some((proxy) => proxy.enabled) ? 'success' : 'warning'" />
            </div>

            <form class="settings-ai-editor" @submit.prevent="saveAiProxySettings">
              <div class="settings-ai-toolbar">
                <div>
                  <strong>渠道列表</strong>
                  <span>最多 3 个通道，按优先级从小到大自动故障切换。</span>
                </div>
                <div class="toolbar-row">
                  <span v-if="aiSaveError" class="inline-status negative">{{ aiSaveError }}</span>
                  <span v-else-if="aiSaveMessage" class="inline-status">{{ aiSaveMessage }}</span>
                  <button type="submit" class="primary-button" :disabled="aiSaving">
                    {{ aiSaving ? '保存中' : '保存 AI 配置' }}
                  </button>
                </div>
              </div>

              <article
                v-for="draft in aiProxyDrafts"
                :key="draft.slot"
                class="settings-ai-channel"
                :class="{ disabled: !draft.enabled }"
              >
                <header>
                  <label class="table-checkbox">
                    <input v-model="draft.enabled" type="checkbox" />
                    <span>{{ draft.slot }} 通道</span>
                  </label>
                  <div class="settings-ai-channel__status">
                    <StatusBadge
                      :label="draft.enabled ? '已启用' : '未启用'"
                      :tone="draft.enabled ? 'success' : 'warning'"
                    />
                    <StatusBadge
                      :label="draft.requires_api_key ? (draft.api_key_configured || draft.api_key ? 'Key 可用' : '未填 Key') : '本地免 Key'"
                      :tone="!draft.requires_api_key || draft.api_key_configured || Boolean(draft.api_key) ? 'success' : 'warning'"
                    />
                    <StatusBadge
                      :label="aiConnectionTestLabel(aiConnectionTestState(draft.slot))"
                      :tone="aiConnectionTestTone(aiConnectionTestState(draft.slot))"
                    />
                    <button
                      type="button"
                      class="compact-button"
                      :disabled="aiConnectionTestState(draft.slot).status === 'testing'"
                      @click="testAiProxyConnection(draft)"
                    >
                      {{ aiConnectionTestState(draft.slot).status === 'testing' ? '测试中' : '测试连接' }}
                    </button>
                  </div>
                </header>

                <div class="settings-ai-form-grid">
                  <div class="form-field">
                    <label>服务商</label>
                    <select v-model="draft.provider" @change="handleProviderChange(draft)">
                      <option
                        v-for="template in providerOptions()"
                        :key="String(template.id)"
                        :value="String(template.id)"
                      >
                        {{ formatProvider(String(template.id)) }}
                      </option>
                    </select>
                  </div>

                  <div class="form-field">
                    <label>协议</label>
                    <select v-model="draft.api_format">
                      <option value="chat_completions">OpenAI Compatible</option>
                      <option value="responses">Responses API</option>
                    </select>
                  </div>

                  <div class="form-field settings-ai-wide">
                    <label>Base URL</label>
                    <input v-model="draft.base_url" placeholder="https://api.example.com/v1" />
                  </div>

                  <div class="form-field">
                    <label>API Key</label>
                    <div class="settings-secret-input">
                      <KeyRound :size="15" />
                      <input
                        v-model="draft.api_key"
                        :type="apiKeyInputType(draft.slot)"
                        :placeholder="apiKeyPlaceholder(draft)"
                      />
                      <button
                        type="button"
                        class="compact-button icon-only-button"
                        :title="visibleApiKeySlots.has(draft.slot) ? '隐藏 API Key' : '显示 API Key'"
                        :aria-label="visibleApiKeySlots.has(draft.slot) ? '隐藏 API Key' : '显示 API Key'"
                        @click="toggleApiKeyVisibility(draft.slot)"
                      >
                        <component :is="visibleApiKeySlots.has(draft.slot) ? EyeOff : Eye" :size="15" />
                      </button>
                    </div>
                  </div>

                  <div class="form-field">
                    <label>模型</label>
                    <input v-model="draft.model" placeholder="模型 ID" />
                  </div>

                  <div class="form-field">
                    <label>优先级</label>
                    <input v-model.number="draft.priority" type="number" min="1" max="99" />
                  </div>
                </div>

                <div class="settings-ai-reference">
                  <span>配置参考</span>
                  <strong>{{ formatProvider(draft.provider) }}</strong>
                  <span>{{ providerTemplateById.get(draft.provider)?.description || '自定义 OpenAI 兼容服务商。' }}</span>
                  <span
                    class="settings-ai-test-message"
                    :class="aiConnectionTestState(draft.slot).status"
                  >
                    {{ aiConnectionTestMessage(draft.slot) }}
                  </span>
                </div>
              </article>
            </form>

            <div class="settings-section__head">
              <div>
                <h3>供应商预设</h3>
                <p>下拉列表来源，实际可用模型仍以服务商账号权限为准。</p>
              </div>
            </div>
            <div class="settings-provider-grid">
              <article
                v-for="template in data.ai_provider_templates"
                :key="String(template.id)"
                class="settings-provider-card"
              >
                <header>
                  <h4>{{ formatProvider(String(template.id)) }}</h4>
                  <StatusBadge
                    :label="templateKeyLabel(template)"
                    :tone="isTruthySetting(template.requires_api_key) ? 'warning' : 'success'"
                  />
                </header>
                <dl class="settings-pairs">
                  <div class="settings-pair-wide">
                    <dt>Base URL</dt>
                    <dd>{{ formatCodeValue(template.base_url) }}</dd>
                  </div>
                  <div>
                    <dt>默认模型</dt>
                    <dd>{{ template.default_model }}</dd>
                  </div>
                  <div>
                    <dt>接口格式</dt>
                    <dd>{{ formatCodeValue(template.api_format) }}</dd>
                  </div>
                </dl>
                <p>{{ template.description }}</p>
              </article>
            </div>
          </section>

          <section v-else-if="activeCategory === 'data'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>行情与本地数据</h3>
                <p>集中查看存储后端、公共行情、新闻情绪和缓存策略。</p>
              </div>
            </div>
            <div class="settings-key-grid">
              <article v-for="item in dataSourceItems" :key="item.key" class="settings-key-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </article>
            </div>

            <div class="settings-section__head">
              <div>
                <h3>新闻采集网站</h3>
                <p>当前新闻情绪模块会从这些 RSS 网站采集资讯。</p>
              </div>
            </div>
            <div class="settings-news-source-grid">
              <article v-for="feed in data.news_feeds" :key="feed.feed_url" class="settings-news-source">
                <div>
                  <strong>{{ feed.name }}</strong>
                  <a :href="feed.website_url" target="_blank" rel="noreferrer">{{ feed.website_url }}</a>
                </div>
                <span>{{ feed.feed_url }}</span>
              </article>
            </div>
          </section>

          <section v-else-if="activeCategory === 'notifications'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>通知渠道</h3>
                <p>管理每日推送计划，保存通知出口，并发送测试消息验证连通性。</p>
              </div>
              <StatusBadge
                :label="`${notificationItems.filter((item) => item.configured).length}/${notificationItems.length} 已配置`"
                :tone="notificationItems.some((item) => item.configured) ? 'success' : 'warning'"
              />
            </div>

            <form class="settings-daily-push-panel" @submit.prevent="handleSaveDailyPushSettings">
              <header>
                <div>
                  <CalendarClock :size="18" />
                  <div>
                    <h4>每日量化日报</h4>
                    <span>按本机本地时间自动生成，并发送到下方已配置的通知渠道。</span>
                  </div>
                </div>
                <div class="settings-ai-channel__status">
                  <StatusBadge :label="dailyPushConfiguredLabel()" :tone="dailyPushTone()" />
                  <button
                    type="button"
                    class="compact-button"
                    :disabled="dailyPushStatus === 'running' || dailyPushStatus === 'saving'"
                    @click="runDailyPushNow"
                  >
                    <Send :size="14" />
                    {{ dailyPushStatus === 'running' ? '推送中' : '立即推送' }}
                  </button>
                  <button
                    type="submit"
                    class="primary-button"
                    :disabled="dailyPushStatus === 'running' || dailyPushStatus === 'saving'"
                  >
                    <Save :size="15" />
                    {{ dailyPushStatus === 'saving' ? '保存中' : '保存推送计划' }}
                  </button>
                </div>
              </header>

              <div class="settings-daily-push-grid">
                <label class="settings-toggle-option">
                  <input v-model="dailyPushDraft.enabled" type="checkbox" />
                  <span>
                    <strong>启用每日推送</strong>
                    <small>{{ dailyPushDraft.enabled ? '调度器将按保存时间推送' : '只保留手动推送' }}</small>
                  </span>
                </label>
                <label class="settings-toggle-option">
                  <input v-model="dailyPushDraft.run_immediately" type="checkbox" />
                  <span>
                    <strong>服务启动后立即推送</strong>
                    <small>{{ dailyPushDraft.run_immediately ? '启动时会先执行一次' : '等待下一个计划时间' }}</small>
                  </span>
                </label>
                <div class="form-field">
                  <label>默认推送时间</label>
                  <input v-model="dailyPushDraft.schedule_time" type="time" />
                </div>
                <div class="form-field settings-daily-push-wide">
                  <label>多时间点</label>
                  <input
                    v-model="dailyPushDraft.schedule_times"
                    placeholder="09:00,18:00；留空则使用默认推送时间"
                  />
                </div>
              </div>

              <div class="settings-notification-message" :class="dailyPushStatus">
                {{ dailyPushResultMessage() }}
              </div>
            </form>

            <form class="settings-notification-editor" @submit.prevent="saveNotificationSettings">
              <div class="settings-ai-toolbar settings-notification-toolbar">
                <div>
                  <strong>测试消息</strong>
                  <span>各渠道测试会先保存当前卡片配置，再使用这里的标题、正文和超时参数发送。</span>
                </div>
                <div class="toolbar-row">
                  <span v-if="notificationSaveError" class="inline-status negative">{{ notificationSaveError }}</span>
                  <span v-else-if="notificationSaveMessage" class="inline-status">{{ notificationSaveMessage }}</span>
                  <button type="submit" class="primary-button" :disabled="notificationSaving">
                    <Save :size="15" />
                    {{ notificationSaving ? '保存中' : '保存通知配置' }}
                  </button>
                </div>
              </div>

              <div class="settings-test-panel settings-notification-test-panel">
                <div class="settings-notification-fields">
                  <div class="form-field">
                    <label>标题</label>
                    <input v-model="notificationTitle" />
                  </div>
                  <div class="form-field">
                    <label>超时秒数</label>
                    <input v-model.number="notificationTimeoutSeconds" type="number" min="1" max="60" />
                  </div>
                  <div class="form-field settings-notification-wide">
                    <label>测试消息</label>
                    <textarea v-model="notificationMessage" rows="3" />
                  </div>
                </div>
              </div>

              <div class="settings-notification-grid">
                <article
                  v-for="item in notificationItems"
                  :key="item.provider"
                  class="settings-notification-card"
                  :class="item.configured ? 'success' : 'warning'"
                >
                  <header>
                    <div>
                      <h4>{{ item.title }}</h4>
                      <span>{{ item.description }}</span>
                    </div>
                    <div class="settings-ai-channel__status">
                      <StatusBadge
                        :label="notificationReadyLabel(item.draft, item)"
                        :tone="item.configured ? 'success' : 'warning'"
                      />
                      <StatusBadge
                        :label="notificationTestLabel(notificationTestState(item.provider))"
                        :tone="notificationTestTone(notificationTestState(item.provider))"
                      />
                      <button
                        type="button"
                        class="compact-button"
                        :disabled="notificationTestState(item.provider).status === 'testing'"
                        @click="testNotification(item.provider)"
                      >
                        <Send :size="14" />
                        {{ notificationTestState(item.provider).status === 'testing' ? '发送中' : '发送测试' }}
                      </button>
                    </div>
                  </header>

                  <div v-if="item.kind === 'webhook'" class="settings-notification-card-fields">
                    <div class="form-field settings-notification-wide">
                      <label>{{ item.webhookLabel }}</label>
                      <div class="settings-secret-input">
                        <KeyRound :size="15" />
                        <input
                          v-model="item.draft.webhook_url"
                          :type="notificationSecretInputType(notificationFieldKey(item.provider, 'webhook_url'))"
                          :placeholder="notificationSecretPlaceholder(item.draft.webhook_configured, item.webhookLabel || 'Webhook')"
                        />
                        <button
                          type="button"
                          class="compact-button icon-only-button"
                          :title="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'webhook_url')) ? '隐藏 Webhook' : '显示 Webhook'"
                          :aria-label="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'webhook_url')) ? '隐藏 Webhook' : '显示 Webhook'"
                          @click="toggleNotificationSecretVisibility(notificationFieldKey(item.provider, 'webhook_url'))"
                        >
                          <component
                            :is="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'webhook_url')) ? EyeOff : Eye"
                            :size="15"
                          />
                        </button>
                      </div>
                    </div>
                  </div>

                  <div v-else-if="item.kind === 'telegram'" class="settings-notification-card-fields">
                    <div class="form-field">
                      <label>Bot Token</label>
                      <div class="settings-secret-input">
                        <KeyRound :size="15" />
                        <input
                          v-model="item.draft.telegram_bot_token"
                          :type="notificationSecretInputType(notificationFieldKey(item.provider, 'telegram_bot_token'))"
                          :placeholder="notificationSecretPlaceholder(item.draft.telegram_bot_token_configured, 'Bot Token')"
                        />
                        <button
                          type="button"
                          class="compact-button icon-only-button"
                          :title="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'telegram_bot_token')) ? '隐藏 Bot Token' : '显示 Bot Token'"
                          :aria-label="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'telegram_bot_token')) ? '隐藏 Bot Token' : '显示 Bot Token'"
                          @click="toggleNotificationSecretVisibility(notificationFieldKey(item.provider, 'telegram_bot_token'))"
                        >
                          <component
                            :is="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'telegram_bot_token')) ? EyeOff : Eye"
                            :size="15"
                          />
                        </button>
                      </div>
                    </div>
                    <div class="form-field">
                      <label>Chat ID</label>
                      <input
                        v-model="item.draft.telegram_chat_id"
                        :placeholder="notificationSecretPlaceholder(item.draft.telegram_chat_id_configured, 'Chat ID')"
                      />
                    </div>
                  </div>

                  <div v-else class="settings-notification-card-fields settings-notification-email-fields">
                    <div class="form-field">
                      <label>SMTP Host</label>
                      <input
                        v-model="item.draft.email_smtp_host"
                        :placeholder="notificationSecretPlaceholder(item.draft.email_smtp_host_configured, 'SMTP Host')"
                      />
                    </div>
                    <div class="form-field">
                      <label>SMTP Port</label>
                      <input v-model.number="item.draft.email_smtp_port" type="number" min="1" max="65535" />
                    </div>
                    <div class="form-field">
                      <label>SMTP Username</label>
                      <input
                        v-model="item.draft.email_smtp_username"
                        :placeholder="notificationSecretPlaceholder(item.draft.email_smtp_username_configured, 'SMTP Username')"
                      />
                    </div>
                    <div class="form-field">
                      <label>SMTP Password</label>
                      <div class="settings-secret-input">
                        <KeyRound :size="15" />
                        <input
                          v-model="item.draft.email_smtp_password"
                          :type="notificationSecretInputType(notificationFieldKey(item.provider, 'email_smtp_password'))"
                          :placeholder="notificationSecretPlaceholder(item.draft.email_smtp_password_configured, 'SMTP Password')"
                        />
                        <button
                          type="button"
                          class="compact-button icon-only-button"
                          :title="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'email_smtp_password')) ? '隐藏 SMTP Password' : '显示 SMTP Password'"
                          :aria-label="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'email_smtp_password')) ? '隐藏 SMTP Password' : '显示 SMTP Password'"
                          @click="toggleNotificationSecretVisibility(notificationFieldKey(item.provider, 'email_smtp_password'))"
                        >
                          <component
                            :is="visibleNotificationSecretFields.has(notificationFieldKey(item.provider, 'email_smtp_password')) ? EyeOff : Eye"
                            :size="15"
                          />
                        </button>
                      </div>
                    </div>
                    <div class="form-field">
                      <label>发件人</label>
                      <input
                        v-model="item.draft.email_from"
                        :placeholder="notificationSecretPlaceholder(item.draft.email_from_configured, '发件人')"
                      />
                    </div>
                    <div class="form-field">
                      <label>收件人</label>
                      <input
                        v-model="item.draft.email_to"
                        :placeholder="notificationSecretPlaceholder(item.draft.email_to_configured, '收件人')"
                      />
                    </div>
                    <label class="settings-toggle-option settings-notification-wide">
                      <input v-model="item.draft.email_use_tls" type="checkbox" />
                      <span>
                        <strong>STARTTLS</strong>
                        <small>{{ item.draft.email_use_tls ? '已开启' : '未开启' }}</small>
                      </span>
                    </label>
                  </div>

                  <div
                    class="settings-notification-message"
                    :class="notificationTestState(item.provider).status"
                  >
                    {{ notificationTestMessage(item.provider) }}
                  </div>
                </article>
              </div>
            </form>
          </section>

          <section v-else-if="activeCategory === 'safety'" class="settings-section">
            <div class="settings-section__head">
              <div>
                <h3>安全检查清单</h3>
                <p>实盘前确认现货边界、权限隔离和紧急停止能力。</p>
              </div>
            </div>
            <div class="settings-card-grid">
              <article
                v-for="item in data.safety_checks"
                :key="item.name"
                class="settings-config-card"
                :class="safetyTone(item.status)"
              >
                <header>
                  <h4>{{ formatStatus(item.name) }}</h4>
                  <StatusBadge :label="formatStatus(item.status)" :tone="safetyTone(item.status)" />
                </header>
              </article>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
