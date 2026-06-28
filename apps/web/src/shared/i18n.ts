import { computed, ref, watch } from 'vue'

export type LanguageCode = 'en' | 'zh'

const LANGUAGE_STORAGE_KEY = 'spotpilot-quant-language'
const translatableAttrs = ['aria-label', 'placeholder', 'title'] as const
const textSources = new WeakMap<Text, string>()
const attrSources = new WeakMap<Element, Map<string, string>>()

let observer: MutationObserver | null = null
let isApplyingTranslation = false

export const languageOptions = [
  { code: 'en' as const, label: 'English', shortLabel: 'EN' },
  { code: 'zh' as const, label: '中文', shortLabel: '中' },
]

export const currentLanguage = ref<LanguageCode>(readInitialLanguage())

export function useLanguage() {
  const isEnglish = computed(() => currentLanguage.value === 'en')
  const isChinese = computed(() => currentLanguage.value === 'zh')

  return {
    language: currentLanguage,
    languageOptions,
    isEnglish,
    isChinese,
    setLanguage,
    t: translateText,
  }
}

export function setLanguage(language: LanguageCode) {
  currentLanguage.value = language
}

export function installDomTranslations(root: ParentNode = document.body) {
  applyDocumentLanguage()
  translateTree(root)

  observer?.disconnect()
  observer = new MutationObserver((mutations) => {
    if (isApplyingTranslation) {
      return
    }

    for (const mutation of mutations) {
      if (mutation.type === 'characterData') {
        translateTextNode(mutation.target as Text)
      } else if (mutation.type === 'attributes') {
        translateElementAttrs(mutation.target as Element)
      } else {
        mutation.addedNodes.forEach((node) => translateTree(node))
      }
    }
  })
  observer.observe(root, {
    attributes: true,
    attributeFilter: [...translatableAttrs],
    childList: true,
    characterData: true,
    subtree: true,
  })
}

export function translateText(value: string) {
  if (currentLanguage.value === 'zh') {
    return value
  }
  return translateKnownText(value)
}

watch(currentLanguage, (language) => {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  }
  applyDocumentLanguage()
  if (typeof document !== 'undefined') {
    translateTree(document.body)
  }
})

function readInitialLanguage(): LanguageCode {
  if (typeof window === 'undefined') {
    return 'en'
  }
  return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === 'zh' ? 'zh' : 'en'
}

function applyDocumentLanguage() {
  if (typeof document === 'undefined') {
    return
  }
  document.documentElement.lang = currentLanguage.value === 'zh' ? 'zh-CN' : 'en'
  document.documentElement.dataset.language = currentLanguage.value
}

function translateTree(node: Node | ParentNode | null) {
  if (!node) {
    return
  }

  if (node.nodeType === Node.TEXT_NODE) {
    translateTextNode(node as Text)
    return
  }

  if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) {
    return
  }

  if (node.nodeType === Node.ELEMENT_NODE) {
    const element = node as Element
    if (['SCRIPT', 'STYLE', 'TEXTAREA'].includes(element.tagName)) {
      return
    }
    translateElementAttrs(element)
  }

  node.childNodes.forEach((child) => translateTree(child))
}

function translateTextNode(node: Text) {
  const source = sourceForTextNode(node)
  if (!source) {
    return
  }

  const nextText = currentLanguage.value === 'zh' ? source : preserveWhitespace(source, translateKnownText(source.trim()))
  if (node.data === nextText) {
    return
  }

  isApplyingTranslation = true
  node.data = nextText
  isApplyingTranslation = false
}

function sourceForTextNode(node: Text) {
  const currentText = node.data
  const currentCore = currentText.trim()
  if (!currentCore) {
    return ''
  }

  const existingSource = textSources.get(node)
  if (existingSource) {
    if (currentText === existingSource || isKnownEnglishTranslation(currentCore, existingSource.trim())) {
      return existingSource
    }
    if (hasKnownTranslation(currentCore)) {
      textSources.set(node, currentText)
      return currentText
    }
    if (currentLanguage.value === 'zh') {
      return existingSource
    }
  }

  if (!hasKnownTranslation(currentCore)) {
    return ''
  }

  textSources.set(node, currentText)
  return currentText
}

function translateElementAttrs(element: Element) {
  for (const attr of translatableAttrs) {
    const value = element.getAttribute(attr)
    if (!value?.trim()) {
      continue
    }

    const source = sourceForAttr(element, attr, value)
    if (!source) {
      continue
    }

    const nextValue = currentLanguage.value === 'zh' ? source : translateKnownText(source)
    if (value === nextValue) {
      continue
    }

    isApplyingTranslation = true
    element.setAttribute(attr, nextValue)
    isApplyingTranslation = false
  }
}

function sourceForAttr(element: Element, attr: string, currentValue: string) {
  let sources = attrSources.get(element)
  const existingSource = sources?.get(attr)
  if (existingSource) {
    if (currentValue === existingSource || isKnownEnglishTranslation(currentValue, existingSource)) {
      return existingSource
    }
    if (hasKnownTranslation(currentValue)) {
      sources?.set(attr, currentValue)
      return currentValue
    }
    if (currentLanguage.value === 'zh') {
      return existingSource
    }
  }

  if (!hasKnownTranslation(currentValue)) {
    return ''
  }

  if (!sources) {
    sources = new Map<string, string>()
    attrSources.set(element, sources)
  }
  sources.set(attr, currentValue)
  return currentValue
}

function preserveWhitespace(source: string, translatedCore: string) {
  const match = source.match(/^(\s*)(.*?)(\s*)$/s)
  if (!match) {
    return translatedCore
  }
  return `${match[1]}${translatedCore}${match[3]}`
}

function hasKnownTranslation(value: string) {
  return translateKnownText(value) !== value
}

function isKnownEnglishTranslation(value: string, source: string) {
  return value === translateKnownText(source)
}

function translateKnownText(value: string): string {
  const direct = translations[value]
  if (direct) {
    return direct
  }

  for (const [pattern, replacer] of patternTranslations) {
    const match = value.match(pattern)
    if (match) {
      return replacer(match)
    }
  }

  return value
}

const translations: Record<string, string> = {
  'SpotPilot Quant': 'SpotPilot Quant',
  '现货量化领航台': 'Spot quant pilot',
  '展开菜单': 'Expand menu',
  '收起菜单': 'Collapse menu',
  '主导航': 'Main navigation',
  '主题切换': 'Theme switcher',
  '深色主题': 'Dark theme',
  '浅色主题': 'Light theme',
  '深色': 'Dark',
  '浅色': 'Light',
  '中文': 'Chinese',
  '语言切换': 'Language switcher',
  '英语': 'English',
  '总览': 'Dashboard',
  '系统状态': 'System status',
  '行情': 'Market',
  'K 线与数据质量': 'Candles and data quality',
  '策略': 'Strategy',
  '参数与信号': 'Parameters and signals',
  '回测': 'Backtest',
  '收益与明细': 'Returns and details',
  'AI分析': 'AI Analysis',
  '评分与过滤': 'Scoring and filters',
  '交易': 'Trading',
  '现货执行': 'Spot execution',
  '风控': 'Risk',
  '限制与熔断': 'Limits and kill switch',
  '日志': 'Logs',
  '审计追踪': 'Audit trail',
  '设置': 'Settings',
  '连接配置': 'Connections',
  '待验证': 'Pending validation',
  '行情未验证': 'Market data unverified',
  '行情刚刚更新': 'Market just updated',

  '刷新': 'Refresh',
  '刷新中': 'Refreshing',
  '加载中': 'Loading',
  '暂无数据': 'No data',
  '出错了': 'Error',
  '已停用': 'Disabled',
  '保存中': 'Saving',
  '保存失败': 'Save failed',
  '保存完成': 'Saved',
  '导出失败': 'Export failed',
  '导出中': 'Exporting',
  '校验中': 'Validating',
  '提交中': 'Submitting',
  '测试中': 'Testing',
  '未测试': 'Not tested',
  '连通正常': 'Connected',
  '连通失败': 'Connection failed',
  '已配置': 'Configured',
  '待配置': 'Not configured',
  '未配置': 'Not configured',
  '已关闭': 'Closed',
  '已开启': 'On',
  '未开启': 'Off',
  '未启用': 'Disabled',
  '可用': 'Available',
  '等待凭证': 'Waiting for credentials',
  '必须关闭': 'Must be disabled',
  '全部正常': 'All normal',
  '实时审计': 'Real-time audit',
  '读取中': 'Loading',
  '筛选': 'Filter',
  '重新生成': 'Regenerate',
  '全部': 'All',
  '时间': 'Time',
  '级别': 'Level',
  '模块': 'Module',
  '消息': 'Message',
  '关联编号': 'Correlation ID',
  '币种': 'Symbol',
  '交易对': 'Symbol',
  '交易所': 'Exchange',
  '数量': 'Quantity',
  '价格': 'Price',
  '均价': 'Average price',
  '浮盈': 'Unrealized PnL',
  '动作': 'Action',
  '原因': 'Reason',
  '状态': 'Status',
  '类型': 'Type',
  '值': 'Value',
  '参数': 'Parameter',
  '规则': 'Rule',
  '阈值': 'Threshold',
  '当前值': 'Current value',
  '触发值': 'Trigger value',
  '方向': 'Side',
  '订单编号': 'Order ID',
  '手续费': 'Fee',
  '操作': 'Action',
  '开仓': 'Opened',
  '平仓': 'Closed',
  '开仓价': 'Entry price',
  '平仓价': 'Exit price',
  '盈亏': 'PnL',
  '退出原因': 'Exit reason',
  '来源': 'Source',
  '标题': 'Title',
  '情绪': 'Sentiment',
  '关键词': 'Keywords',
  '风险': 'Risk',
  '覆盖': 'Coverage',
  '分析对象': 'Target',
  '情绪分': 'Sentiment score',
  '事件风险': 'Event risk',

  '集中查看资产、现货持仓、策略信号、AI判断、风控状态和最新日志。':
    'View assets, spot positions, strategy signals, AI decisions, risk status, and recent logs in one place.',
  '正在加载系统总览': 'Loading dashboard',
  '资产曲线 / 收益曲线': 'Equity / Return Curve',
  '模拟运行账户权益': 'Dry-run account equity',
  '资产曲线': 'Equity curve',
  '当前现货持仓': 'Current Spot Positions',
  '只展示已有现货': 'Existing spot holdings only',
  '最新策略信号': 'Latest Strategy Signals',
  'AI分析 / 风控拦截可追踪': 'AI analysis and risk blocks are traceable',
  'AI市场判断': 'AI Market View',
  '市场状态': 'Market regime',
  '结构化输出': 'Structured output',
  '风险等级': 'Risk level',
  '允许方向': 'Allowed direction',
  'AI分析不直接下单': 'AI analysis cannot place orders directly',
  '最新日志': 'Latest Logs',
  '审计链路': 'Audit chain',

  '查看现货行情、周期、数据源、指标和数据完整性。':
    'Inspect spot prices, timeframes, data sources, indicators, and data integrity.',
  '最新价': 'Last price',
  '24h 涨跌': '24h change',
  '现货市场': 'Spot market',
  '成交量': 'Volume',
  '24 小时基础成交量': '24h base volume',
  '波动率': 'Volatility',
  '已实现波动率': 'Realized volatility',
  '强弱指标': 'RSI',
  '均线 / 平滑异同指标待叠加': 'MA / MACD overlays pending',
  '数据质量': 'Data quality',
  'K 线图 + 成交量 + 指标叠加': 'Candlesticks + Volume + Indicator Overlays',
  '行情表': 'Market Table',
  '缺失 K 线、延迟、异常价格需要明确提示': 'Missing candles, latency, and abnormal prices are surfaced clearly',
  '涨跌幅': 'Change',
  '数据状态': 'Data status',
  '正在加载更早 K 线': 'Loading earlier candles',

  '策略实验室': 'Strategy Lab',
  '策略管理中心统一注册 MA、RSI、网格和 AI 过滤节点，并把信号交给后续风控链路。':
    'The strategy registry manages MA, RSI, grid, and AI filter nodes, then sends signals into the risk pipeline.',
  '策略管理中心统一注册趋势、回归、网格、突破、定投和风控过滤节点，并把信号交给后续风控链路。':
    'The strategy registry manages trend, mean-reversion, grid, breakout, DCA, and risk-filter nodes, then sends signals into the risk pipeline.',
  '生成中': 'Generating',
  '生成策略信号': 'Generate Signals',
  '保存策略参数': 'Save Strategy Parameters',
  '正在加载策略列表': 'Loading strategy list',
  '注册策略': 'Registered strategies',
  '已启用': 'Enabled',
  '信号策略': 'Signal strategies',
  '可回测': 'Backtestable',
  '策略管理中心': 'Strategy Registry',
  '统一注册表': 'Unified registry',
  '启用': 'Enable',
  '停用': 'Disable',
  '详情': 'Details',
  '只产生现货信号': 'Spot signals only',
  '策略模式': 'Strategy mode',
  '禁止开空 / 加杠杆': 'No shorts / leverage',
  '无信号输出': 'No signal output',
  '不可回测': 'Not backtestable',
  '策略参数': 'Strategy parameter',
  '风控参数': 'Risk parameter',
  '最近信号': 'Recent Signals',
  '展示是否被AI分析 / 风控拦截': 'Shows AI analysis and risk blocks',
  '原因 / 拦截': 'Reason / Block',
  '暂无策略说明': 'No strategy description',
  '支持信号生成': 'Signal generation',
  '不生成信号': 'No signal output',
  '支持回测': 'Backtest support',
  '不参与回测': 'No backtest support',
  '可进入实盘链路': 'Can enter live pipeline',
  '不直接实盘': 'No direct live trading',
  '能力': 'Capabilities',
  '模式已更新': 'mode updated',
  '信号生成失败': 'Signal generation failed',

  '用历史 K 线回放验证策略，页面展示的是模拟成交，不是真实订单。':
    'Replay historical candles to validate strategies. Results are simulated fills, not real orders.',
  '仍在同步': 'Still syncing',
  '同步中': 'Syncing',
  '同步历史数据': 'Sync History',
  '导出 JSON': 'Export JSON',
  '导出 CSV': 'Export CSV',
  '运行回测': 'Run Backtest',
  '回测参数': 'Backtest Parameters',
  '来自策略管理中心': 'From strategy registry',
  '开始日期': 'Start date',
  '结束日期': 'End date',
  '初始资金': 'Initial capital',
  '费率': 'Fee rate',
  '滑点': 'Slippage',
  '同步较慢': 'Sync is slow',
  '同步 1m 大范围数据会比较慢，请保持页面打开。':
    'Syncing a wide 1m range can take a while. Keep this page open.',
  '策略加载中': 'Loading strategies',
  '策略加载失败': 'Strategy load failed',
  '正在读取策略管理中心': 'Reading strategy registry',
  '回测结果': 'Backtest Results',
  '正在运行回测': 'Running backtest',
  '历史回测模拟完成': 'Historical backtest simulation complete',
  '模拟收益': 'Simulated return',
  '扣除费用后的收益': 'Return after fees',
  '最大回撤': 'Max drawdown',
  '最大资金回落': 'Largest equity decline',
  '胜率': 'Win rate',
  '回测资产曲线': 'Backtest equity curve',
  '设置回测参数后点击运行回测': 'Set parameters, then run the backtest',
  '历史回测模拟成交': 'Historical Simulated Fills',
  '由历史 K 线回放生成，非真实订单': 'Generated from historical candles, not real orders',
  '请选择可回测策略': 'Select a backtestable strategy',
  '回测失败': 'Backtest failed',
  '历史行情同步失败': 'Historical data sync failed',

  '风控中心': 'Risk Center',
  '管理单笔亏损、单日亏损、最大回撤、仓位上限、连续亏损暂停和AI分析高风险暂停。':
    'Manage per-trade loss, daily loss, max drawdown, position caps, loss streak pauses, and high-risk AI pauses.',
  '正在加载风控状态': 'Loading risk status',
  '当前状态': 'Current status',
  '规则总数': 'Total rules',
  'P0 风控检查项': 'P0 risk checks',
  '待关注规则': 'Rules needing attention',
  '状态非通过的规则': 'Rules not passing',
  '限制动作': 'Restricted actions',
  '禁止或降仓动作': 'Block or reduce actions',
  '审计事件': 'Audit events',
  '风控拦截链路': 'Risk block chain',
  '风控规则': 'Risk Rules',
  '当前值 / 阈值': 'Current value / threshold',
  '风控事件': 'Risk Events',
  '所有拦截必须可追溯': 'Every block must be traceable',
  '暂无风控事件': 'No risk events',
  '全局暂停': 'Global pause',
  '账户余额来源': 'Account balance source',
  '数据延迟': 'Data latency',
  '单笔最大亏损': 'Max single-trade loss',
  '单日最大亏损': 'Max daily loss',
  '单币最大仓位': 'Max symbol position',
  '总仓位上限': 'Total position limit',
  '连续亏损暂停': 'Loss streak pause',
  'AI 高风险暂停': 'AI high-risk pause',
  'Kill Switch 已触发，禁止新开仓并要求撤销挂单。':
    'Kill Switch is armed. New entries are blocked and open orders should be canceled.',
  '系统已暂停策略开仓，仅允许管理已有现货仓位。':
    'Strategy entries are paused. Only existing spot positions can be managed.',
  '未配置账户余额来源，默认暂停新开仓。':
    'Account balance source is not configured. New entries are paused by default.',
  '行情数据延迟或不可用，禁止新开仓。':
    'Market data is delayed or unavailable. New entries are blocked.',
  '单笔浮动亏损超过阈值，要求减仓或人工检查。':
    'Single-position floating loss exceeded the threshold. Reduce exposure or review manually.',
  '账户当日亏损代理指标超过阈值，禁止新开仓。':
    'Daily loss proxy exceeded the threshold. New entries are blocked.',
  '缺少权益曲线来源，暂不触发自动拦截。':
    'Equity curve source is missing. Automatic blocking is not triggered.',
  '单币现货仓位超过阈值，要求降低该币种风险暴露。':
    'Single-symbol spot exposure exceeded the threshold. Reduce that symbol exposure.',
  '总现货仓位超过阈值，禁止新开仓。':
    'Total spot exposure exceeded the threshold. New entries are blocked.',
  '连续亏损或连续拒单达到阈值，暂停策略开仓。':
    'Loss or rejection streak reached the threshold. Strategy entries are paused.',
  'AI 风险等级或允许方向禁止新开仓。':
    'AI risk level or allowed direction blocks new entries.',
  '风控禁止新开仓：允许撤单、持有或卖出现有现货仓位。':
    'Risk blocks new entries: cancel, hold, or sell existing spot positions only.',
  '风控要求降低仓位：仅允许减仓、撤单和风险处置。':
    'Risk requires lower exposure: reduce, cancel, and risk-handling actions only.',
  'P0 风控检查通过，仅允许现货 dry-run 或已确认的 Spot Live 动作。':
    'P0 risk checks passed. Only spot dry-run or confirmed Spot Live actions are allowed.',

  '交易执行': 'Trade Execution',
  '第一版只允许现货模拟运行 / 小额实盘验证，禁止合约、杠杆、保证金和裸空。':
    'The first version only allows spot dry-run and small live validation. Futures, leverage, margin, and naked shorts are prohibited.',
  '交易运行模式': 'Trading mode',
  '模拟运行': 'Dry run',
  '小额实盘': 'Small live',
  '正在加载交易摘要': 'Loading trading summary',
  '模式': 'Mode',
  '现货交易': 'Spot trading',
  '账户余额': 'Account balance',
  '来自本地资产记录': 'From local portfolio records',
  '当前持仓': 'Current positions',
  '只展示现货持仓': 'Spot positions only',
  '当前挂单': 'Open orders',
  '撤单可审计': 'Cancel actions are audited',
  '合约禁用': 'Futures disabled',
  '永续 / 交割合约已禁用': 'Perpetual / delivery futures disabled',
  '卖出只允许卖出现有持仓': 'Sells are limited to existing positions',
  '现货多头': 'Spot long',
  '止损': 'Stop loss',
  '止盈': 'Take profit',
  '当前价': 'Current price',
  '防止遗留订单': 'Prevent stale orders',
  '操作区': 'Order Desk',
  '真实动作必须二次确认': 'Real actions require confirmation',
  '当前模式': 'Current mode',
  '市价': 'Market',
  '限价': 'Limit',
  '模拟校验': 'Dry-run validate',
  '实盘下单': 'Place live order',
  '恢复策略': 'Resume strategy',
  '暂停策略': 'Pause strategy',
  '紧急停止': 'Kill switch',
  '历史订单': 'Order History',
  '用于对账和复盘': 'For reconciliation and review',
  '确认': 'Confirm',
  '取消': 'Cancel',
  '确认切换': 'Switch',
  '继续模拟': 'Keep dry-run',
  '切换到小额实盘': 'Switch to small live',
  '已切换到小额实盘': 'Switched to small live',
  '已保留模拟运行': 'Kept dry-run mode',
  '已取消操作': 'Action cancelled',
  '确认实盘现货下单': 'Confirm live spot order',
  '确认撤销现货挂单': 'Confirm cancel spot order',
  '确认手动平仓': 'Confirm manual close',
  '确认触发紧急停止': 'Confirm kill switch',
  '触发紧急停止': 'Trigger kill switch',
  '已取消紧急停止': 'Kill switch cancelled',
  'dryRun订单校验失败': 'Dry-run order validation failed',
  '实盘只支持买入或卖出现货，请使用单独的撤单按钮':
    'Live mode only supports buying or selling existing spot. Use the separate cancel button for cancels.',
  '实盘订单提交失败': 'Live order submission failed',
  '撤单失败': 'Cancel failed',
  '手动平仓失败': 'Manual close failed',
  '策略开仓已暂停': 'Strategy entries paused',
  '策略开仓已恢复': 'Strategy entries resumed',
  '系统控制状态更新失败': 'System control update failed',
  '紧急停止已触发，后端风控将拒绝新开仓': 'Kill switch triggered. Backend risk checks will reject new entries.',
  '紧急停止触发失败': 'Kill switch trigger failed',

  '按市场、交易对和新闻上下文生成结构化评分和过滤条件，保留风险、数据质量和模型证据。':
    'Generate structured scores and filters by market, symbol, and news context while preserving risk, data quality, and model evidence.',
  '筛选与目标': 'Filters and Target',
  '生成当前对象的最新AI建议信号': 'Generate the latest AI decision signal for the selected target',
  '生成当前对象的最新 AI 建议信号': 'Generate the latest AI decision signal for the selected target',
  '大盘': 'Market',
  '单币种': 'Single symbol',
  '全部动作': 'All actions',
  '全部状态': 'All statuses',
  '买入': 'Buy',
  '加仓': 'Add',
  '持有': 'Hold',
  '减仓': 'Reduce',
  '卖出': 'Sell',
  '观察': 'Watch',
  '回避': 'Avoid',
  '警报': 'Alert',
  '有效': 'Active',
  '已过期': 'Expired',
  '已失效': 'Invalidated',
  '已归档': 'Archived',
  '全市场': 'Market',
  '聚合主流币种新闻、监管和系统性风险': 'Aggregates major-coin news, regulation, and systemic risk',
  '新闻情绪和现货过滤': 'news sentiment and spot filters',
  'AI建议信号': 'AI decision signal',
  '信号数': 'Signals',
  '有效信号': 'Active signals',
  '默认展示active信号': 'Active signals shown by default',
  '默认展示 active 信号': 'Active signals shown by default',
  '防御信号': 'Defensive signals',
  '减仓 / 卖出 / 回避 / 警报': 'Reduce / sell / avoid / alert',
  '进攻信号': 'Bullish signals',
  '买入 / 加仓': 'Buy / add',
  '平均置信度': 'Average confidence',
  '按当前列表统计': 'Based on current list',
  '按币种查询最新信号': 'Find Latest Signal by Symbol',
  '直接生成该交易对最新active信号': 'Generate the latest active signal for a symbol',
  '直接生成该交易对最新 active 信号': 'Generate the latest active signal for a symbol',
  '查询中': 'Searching',
  '查询最新': 'Search latest',
  '该标的暂未生成AI建议信号': 'No AI decision signal has been generated for this symbol',
  '该标的暂未生成 AI 建议信号': 'No AI decision signal has been generated for this symbol',
  '查询最新信号失败': 'Failed to query latest signal',
  '当前筛选条件下没有可展示的AI建议信号': 'No AI decision signals match the current filters',
  '当前筛选条件下没有可展示的 AI 建议信号': 'No AI decision signals match the current filters',
  '评分': 'Score',
  '置信度': 'Confidence',
  '周期': 'Horizon',
  '入场区间': 'Entry range',
  '目标价': 'Target price',
  '理由': 'Reason',
  '催化': 'Catalyst',
  '观察条件': 'Watch conditions',
  '计划质量': 'Plan quality',
  '阶段': 'Phase',
  '过期': 'Expires',
  '查看详情': 'Details',
  'AI分析依据': 'AI Rationale',
  'AI返回结果': 'AI result',
  'AI 返回结果': 'AI result',
  '本地结构校验': 'Local schema validation',
  '结构化结果': 'Structured Result',
  '新闻情绪': 'News Sentiment',
  '刷新新闻': 'Refresh news',
  '正在抓取新闻情绪': 'Fetching news sentiment',
  '结构校验': 'Schema Validation',
  '英文字段 / 英文枚举': 'English fields / English enums',
  '校验结构化内容': 'Validate structured payload',
  '无信号': 'No signal',
  '按需读取': 'On demand',
  '点击刷新新闻读取最新情绪': 'Refresh news to load the latest sentiment',
  '信号详情': 'Signal Details',
  '关闭详情': 'Close details',
  '来源报告': 'Source report',
  '创建时间': 'Created at',
  '过期时间': 'Expires at',
  '价格计划': 'Price Plan',
  '详情视图': 'Detail view',
  '摘要': 'Summary',
  '证据': 'Evidence',
  '元数据': 'Metadata',
  '失效条件': 'Invalidation',
  '结构校验失败': 'Schema validation failed',

  '日志列表': 'Log List',
  '记录策略、智能分析、风控、交易、数据和接口错误，保证每次决策可追溯。':
    'Records strategy, AI, risk, trading, data, and API errors so every decision stays traceable.',
  '智能分析': 'AI analysis',
  '接口错误': 'API errors',
  '接口请求超时': 'API request timed out',
  '正在加载日志': 'Loading logs',
  '当前筛选没有日志': 'No logs match the current filter',

  '项目设置': 'Project Settings',
  '按配置分类管理交易所接口、AI模型通道、数据源、通知和安全检查。':
    'Manage exchange APIs, AI model channels, data sources, notifications, and safety checks by category.',
  '按配置分类管理交易所接口、AI 模型通道、数据源、通知和安全检查。':
    'Manage exchange APIs, AI model channels, data sources, notifications, and safety checks by category.',
  '正在加载设置摘要': 'Loading settings summary',
  '配置分类': 'Settings categories',
  '按模块整理设置摘要。': 'Settings summaries grouped by module.',
  '当前分类': 'Current category',
  '基础设置': 'Basic Settings',
  '交易所接口、默认标的和运行周期。': 'Exchange APIs, default symbol, and runtime interval.',
  '确认默认交易上下文与现货接口权限，后续行情、策略和交易动作都会沿用这些基础参数。':
    'Confirm the default trading context and spot API permissions used by market, strategy, and trading workflows.',
  '账号绑定': 'Account Binding',
  '币安、OKX API Key 与现货权限。': 'Binance / OKX API keys and spot permissions.',
  '绑定交易所私有API，用于读取账户余额、持仓、挂单，并在安全闸门允许后发送现货下单或撤单请求。':
    'Bind private exchange APIs to read balances, positions, and open orders, then place or cancel spot orders after safety gates pass.',
  '绑定交易所私有 API，用于读取账户余额、持仓、挂单，并在安全闸门允许后发送现货下单或撤单请求。':
    'Bind private exchange APIs to read balances, positions, and open orders, then place or cancel spot orders after safety gates pass.',
  'AI模型': 'AI Models',
  'AI 模型': 'AI Models',
  '多模型供应商、通道和优先级。': 'Multi-provider channels and priorities.',
  '管理OpenAI兼容、DeepSeek、通义千问、Kimi、GLM、MiniMax、Ollama等模型通道，并按优先级故障切换。':
    'Manage OpenAI-compatible, DeepSeek, Qwen, Kimi, GLM, MiniMax, Ollama, and other model channels with priority failover.',
  '管理 OpenAI 兼容、DeepSeek、通义千问、Kimi、GLM、MiniMax、Ollama 等模型通道，并按优先级故障切换。':
    'Manage OpenAI-compatible, DeepSeek, Qwen, Kimi, GLM, MiniMax, Ollama, and other model channels with priority failover.',
  '数据源': 'Data Sources',
  '行情、新闻、本地存储和延迟阈值。': 'Market data, news, local storage, and latency thresholds.',
  '汇总公共行情、本地仓储、新闻情绪和缓存配置，用来判断回测与实时分析的数据来源。':
    'Summarizes public market data, local persistence, news sentiment, and cache settings used by backtests and live analysis.',
  '通知渠道': 'Notifications',
  '企业微信、TG、邮箱和 Webhook。': 'WeCom, Telegram, email, and webhooks.',
  '检查告警出口是否可用，并直接选择渠道发送一条测试消息验证链路。':
    'Check alert channels and send a test message to verify delivery.',
  '管理每日推送计划，保存通知出口，并发送测试消息验证连通性。':
    'Manage the daily push schedule, save notification channels, and send test messages to verify connectivity.',
  '安全检查': 'Safety Checks',
  '实盘前的权限与熔断条件。': 'Permissions and kill-switch conditions before live trading.',
  '聚合现货边界、提现权限、实盘确认和紧急停止状态，作为上线前的最后检查。':
    'Aggregates spot boundaries, withdrawal permissions, live confirmation, and kill-switch status as the final pre-live check.',
  '等待设置摘要': 'Waiting for settings summary',
  '默认交易上下文': 'Default Trading Context',
  '影响行情加载、策略筛选和下单表单的默认范围。':
    'Controls the default scope for market loading, strategy filtering, and order forms.',
  '自定义币种': 'Custom Symbols',
  '添加后会出现在行情、AI分析和回测的币种下拉框中。':
    'Added symbols appear in Market, AI Analysis, and Backtest dropdowns.',
  '添加后会出现在行情、AI 分析和回测的币种下拉框中。':
    'Added symbols appear in Market, AI Analysis, and Backtest dropdowns.',
  '添加币种': 'Add Symbol',
  '内置默认币种': 'Built-in Symbols',
  '删除自定义币种': 'Delete custom symbol',
  '暂无自定义币种': 'No custom symbols',
  '例如 PEPE/USDT': 'e.g. PEPE/USDT',
  '交易所接口': 'Exchange APIs',
  '保留现货交易边界，提现权限必须关闭。': 'Keep spot-only boundaries. Withdrawal permission must stay disabled.',
  '公共行情': 'Public market data',
  '沙盒环境': 'Sandbox',
  '提现权限': 'Withdrawal permission',
  '交易所账号绑定': 'Exchange Account Binding',
  '保存私有API后，系统才能读取真实账户余额、持仓和未成交挂单。':
    'After saving private APIs, the system can read real balances, positions, and open orders.',
  '保存私有 API 后，系统才能读取真实账户余额、持仓和未成交挂单。':
    'After saving private APIs, the system can read real balances, positions, and open orders.',
  '账号列表': 'Accounts',
  '密钥不会回显；留空保存会继续保留后端已有密钥。':
    'Secrets are never echoed. Leave them blank to keep saved backend credentials.',
  '保存账号绑定': 'Save Accounts',
  '凭证已配置': 'Credentials configured',
  '待配置凭证': 'Credentials needed',
  '现货已启用': 'Spot enabled',
  '现货未启用': 'Spot disabled',
  '测试连接': 'Test connection',
  '隐藏APIKey': 'Hide API Key',
  '显示APIKey': 'Show API Key',
  '隐藏 API Key': 'Hide API Key',
  '显示 API Key': 'Show API Key',
  '隐藏 API Secret': 'Hide API Secret',
  '显示 API Secret': 'Show API Secret',
  '隐藏 Passphrase': 'Hide Passphrase',
  '显示 Passphrase': 'Show Passphrase',
  '现货交易接口': 'Spot trading API',
  '允许读取持仓与挂单操作': 'Allows positions, open orders, and trading actions',
  '仅保存凭证，不启用私有交易': 'Save credentials only; private trading disabled',
  '余额与持仓读取': 'Balances and positions',
  '挂单与撤单': 'Open orders and cancels',
  '交易所接口已启用': 'Exchange API enabled',
  '交易所接口未启用': 'Exchange API disabled',
  '全局实盘闸门': 'Global live gate',
  'AI模型通道': 'AI Model Channels',
  'AI 模型通道': 'AI Model Channels',
  '选择服务商后自动带出协议、BaseURL和模型示例，再填APIKey保存。':
    'Selecting a provider fills protocol, Base URL, and example model. Add an API key and save.',
  '选择服务商后自动带出协议、Base URL 和模型示例，再填 API Key 保存。':
    'Selecting a provider fills protocol, Base URL, and example model. Add an API key and save.',
  '渠道列表': 'Channels',
  '最多3个通道，按优先级从小到大自动故障切换。':
    'Up to 3 channels. Lower priority numbers fail over first.',
  '最多 3 个通道，按优先级从小到大自动故障切换。':
    'Up to 3 channels. Lower priority numbers fail over first.',
  '保存AI配置': 'Save AI Settings',
  '保存 AI 配置': 'Save AI Settings',
  '通道': 'Channel',
  '已启用通道': 'Channel enabled',
  '未启用通道': 'Channel disabled',
  'Key可用': 'Key available',
  'Key 可用': 'Key available',
  '未填Key': 'Missing key',
  '未填 Key': 'Missing key',
  '本地免Key': 'No local key needed',
  '本地免 Key': 'No local key needed',
  '隐藏 Webhook': 'Hide Webhook',
  '显示 Webhook': 'Show Webhook',
  '隐藏 Bot Token': 'Hide Bot Token',
  '显示 Bot Token': 'Show Bot Token',
  '隐藏 SMTP Password': 'Hide SMTP Password',
  '显示 SMTP Password': 'Show SMTP Password',
  '服务商': 'Provider',
  '协议': 'Protocol',
  '模型': 'Model',
  '优先级': 'Priority',
  '模型ID': 'Model ID',
  '模型 ID': 'Model ID',
  '配置参考': 'Configuration reference',
  '自定义OpenAI兼容服务商。': 'Custom OpenAI-compatible provider.',
  '自定义 OpenAI 兼容服务商。': 'Custom OpenAI-compatible provider.',
  '供应商预设': 'Provider Presets',
  '下拉列表来源，实际可用模型仍以服务商账号权限为准。':
    'Dropdown source. Actual model availability still depends on provider account permissions.',
  '默认模型': 'Default model',
  '接口格式': 'API format',
  '行情与本地数据': 'Market and Local Data',
  '集中查看存储后端、公共行情、新闻情绪和缓存策略。':
    'Review storage backend, public market data, news sentiment, and cache policy.',
  '新闻采集网站': 'News Feeds',
  '当前新闻情绪模块会从这些RSS网站采集资讯。':
    'The news sentiment module collects items from these RSS feeds.',
  '当前新闻情绪模块会从这些 RSS 网站采集资讯。':
    'The news sentiment module collects items from these RSS feeds.',
  '保存企业微信、Telegram、邮箱、Slack、Discord和飞书的通知出口，并发送测试消息验证连通性。':
    'Save WeCom, Telegram, email, Slack, Discord, and Feishu notification channels, then send test messages.',
  '保存企业微信、Telegram、邮箱、Slack、Discord 和飞书的通知出口，并发送测试消息验证连通性。':
    'Save WeCom, Telegram, email, Slack, Discord, and Feishu notification channels, then send test messages.',
  '每日量化日报': 'Daily Quant Report',
  '按本机本地时间自动生成，并发送到下方已配置的通知渠道。':
    'Automatically generated on the machine local time and sent to configured channels below.',
  '推送中': 'Pushing',
  '立即推送': 'Push now',
  '保存推送计划': 'Save Push Schedule',
  '启用每日推送': 'Enable daily push',
  '调度器将按保存时间推送': 'The scheduler will push at the saved time',
  '只保留手动推送': 'Manual push only',
  '服务启动后立即推送': 'Push once after service starts',
  '启动时会先执行一次': 'Runs once on startup',
  '等待下一个计划时间': 'Wait for the next scheduled time',
  '默认推送时间': 'Default push time',
  '多时间点': 'Multiple times',
  '09:00,18:00；留空则使用默认推送时间': '09:00,18:00; leave blank to use the default push time',
  '开启后调度器会按保存的时间自动生成并推送日报。':
    'When enabled, the scheduler will generate and push the daily report at the saved time.',
  '默认推送时间需要使用 HH:MM 格式': 'Default push time must use HH:MM format',
  '每日推送配置已保存': 'Daily push settings saved',
  '保存每日推送配置失败': 'Failed to save daily push settings',
  '正在生成并发送每日量化日报': 'Generating and sending the daily quant report',
  '正在发送每日量化日报': 'Sending the daily quant report',
  '每日量化日报已发送': 'Daily quant report sent',
  '日报生成完成，但没有成功送达的渠道': 'Report generated, but no channel delivered successfully',
  '立即推送失败': 'Push now failed',
  '测试消息': 'Test Message',
  '各渠道测试会先保存当前卡片配置，再使用这里的标题、正文和超时参数发送。':
    'Each channel test saves the card first, then sends with this title, body, and timeout.',
  '保存通知配置': 'Save Notifications',
  '超时秒数': 'Timeout seconds',
  '正文': 'Body',
  '发送中': 'Sending',
  '发送测试': 'Send test',
  '已发送': 'Sent',
  '待检查': 'Needs check',
  '发件人': 'Sender',
  '收件人': 'Recipient',
  '安全检查清单': 'Safety Checklist',
  '实盘前确认现货边界、权限隔离和紧急停止能力。':
    'Before live trading, confirm spot boundaries, permission isolation, and kill-switch capability.',
  '需要Key': 'Key required',
  '需要 Key': 'Key required',
  '请选择服务商': 'Select a provider',
  '请填写BaseURL': 'Enter Base URL',
  '请填写模型ID': 'Enter model ID',
  '请填写 Base URL': 'Enter Base URL',
  '请填写模型 ID': 'Enter model ID',
  '该服务商需要 API Key': 'This provider requires an API key',
  '该服务商需要APIKey': 'This provider requires an API key',
  '正在测试模型连通性': 'Testing model connectivity',
  '模型连通性测试失败': 'Model connectivity test failed',
  '通知渠道配置已保存': 'Notification channels saved',
  '通知测试失败': 'Notification test failed',
  '正在保存并发送测试通知': 'Saving and sending test notification',
  '交易所账号绑定已保存': 'Exchange accounts saved',
  '正在测试交易所账号连通性': 'Testing exchange account connectivity',
  '交易所账号连通性测试失败': 'Exchange account connectivity test failed',
  'AI模型配置已保存': 'AI model settings saved',
  'AI 模型配置已保存': 'AI model settings saved',
  'SMTP 端口需要在 1 到 65535 之间': 'SMTP port must be between 1 and 65535',
  '成功': 'Succeeded',
  '失败': 'Failed',
  '使用已保存 Key': 'using saved key',
  '使用已保存凭证': 'using saved credentials',
  '多时间点格式不正确': 'Invalid multiple-time format',

  '企业微信': 'WeCom',
  '邮箱': 'Email',
  '飞书': 'Feishu',
  '企业微信群机器人Webhook，适合内部告警群。': 'WeCom group bot webhook for internal alert groups.',
  '企业微信群机器人 Webhook，适合内部告警群。': 'WeCom group bot webhook for internal alert groups.',
  '通过BotAPI向指定chat_id发送消息。': 'Sends messages to a chat_id through the Bot API.',
  '通过 Bot API 向指定 chat_id 发送消息。': 'Sends messages to a chat_id through the Bot API.',
  '使用SMTP向指定收件人发送测试邮件。': 'Uses SMTP to send a test email to recipients.',
  '使用 SMTP 向指定收件人发送测试邮件。': 'Uses SMTP to send a test email to recipients.',
  'SlackIncomingWebhook，用于频道告警。': 'Slack incoming webhook for channel alerts.',
  'Slack Incoming Webhook，用于频道告警。': 'Slack incoming webhook for channel alerts.',
  'DiscordWebhook，用于频道或服务器通知。': 'Discord webhook for channel or server notifications.',
  'Discord Webhook，用于频道或服务器通知。': 'Discord webhook for channel or server notifications.',
  '保留原飞书群机器人Webhook通道。': 'Keeps the original Feishu group bot webhook channel.',
  '保留原飞书群机器人 Webhook 通道。': 'Keeps the original Feishu group bot webhook channel.',
  '企业微信群机器人Webhook': 'WeCom group bot webhook',
  '企业微信群机器人 Webhook': 'WeCom group bot webhook',
  '飞书群机器人Webhook': 'Feishu group bot webhook',
  '飞书群机器人 Webhook': 'Feishu group bot webhook',

  '允许交易': 'Trading allowed',
  '仅允许减仓': 'Reduce only',
  '当前禁止新开仓': 'New entries blocked',
  '策略已暂停': 'Strategy paused',
  '允许': 'Allow',
  '正常': 'Normal',
  '暂停': 'Pause',
  '风控拒绝': 'Rejected by risk',
  '现货持仓不足，无法卖出': 'Insufficient spot position to sell',
  '撤单校验通过': 'Cancel validation passed',
  '观望校验通过': 'Hold validation passed',
  '模拟校验通过': 'Dry-run validation passed',
  '待处理': 'Pending',
  '挂单中': 'Open',
  '已成交': 'Filled',
  '已撤销': 'Canceled',
  '已拒绝': 'Rejected',
  '已完成': 'Completed',
  '同步失败': 'Sync failed',
  '交易所异常': 'Exchange error',
  '抓取失败': 'Fetch failed',
  '本地数据库不可用': 'Local database unavailable',
  '日期范围无效': 'Invalid date range',
  '暂不支持该策略': 'Unsupported strategy',
  '找不到策略': 'Strategy not found',
  '策略已停用': 'Strategy disabled',
  '缺少历史行情': 'Historical data unavailable',
  '参数无效': 'Invalid parameters',
  '可运行': 'Ready',
  '后续版本支持': 'Planned for later version',
  '只做结构校验': 'Schema validation only',
  '已通过': 'Passed',
  '必须确认': 'Required',
  '连接正常': 'Healthy',
  '部分可用': 'Degraded',
  '未连接': 'Offline',
  '提示': 'Info',
  '注意': 'Warning',
  '紧急': 'Critical',
  '正面': 'Positive',
  '中性': 'Neutral',
  '负面': 'Negative',
  '已拦截': 'Blocked',
  '只允许现货': 'Spot only',
  '合约已禁用': 'Futures disabled',
  '实盘二次确认': 'Live confirmation',
  '账户': 'Account',
  '暂未接入': 'N/A',
  '卖出现货': 'Sell spot',
  '观望': 'Hold',
  '撤单': 'Cancel',
  '做多': 'Long',
  '仅做多': 'Long only',
  '仅减仓': 'Reduce only',
  '双向': 'Both',
  '禁止交易': 'No trading',
  '市价单': 'Market order',
  '限价单': 'Limit order',
  '仅回测': 'Backtest only',
  '只做风控过滤': 'Risk filter only',
  '风控过滤': 'Risk filter',
  '低风险': 'Low risk',
  '中等风险': 'Medium risk',
  '高风险': 'High risk',
  '极高风险': 'Extreme risk',
  '趋势行情': 'Trending',
  '震荡行情': 'Range-bound',
  '剧烈波动': 'Volatile',
  '新闻偏正面': 'News positive',
  '新闻中性': 'News neutral',
  '新闻偏负面': 'News negative',
  'AI模型通道不可用': 'AI channel unavailable',
  'AI 模型通道不可用': 'AI channel unavailable',
  '模型通道不可用，新闻偏正面': 'AI unavailable, news positive',
  '模型通道不可用，新闻中性': 'AI unavailable, news neutral',
  '模型通道不可用，新闻偏负面': 'AI unavailable, news negative',
  '结构异常': 'Invalid structure',
  '暂未配置': 'Not configured',
  '币安': 'Binance',
  '布林带回归': 'Bollinger Bands',
  'MACD 趋势': 'MACD Trend',
  '趋势回踩': 'Trend Pullback',
  '定投建仓': 'DCA',
  '资金费率过滤': 'Funding Rate Guard',
  'OpenAI兼容': 'OpenAI compatible',
  'OpenAI 兼容': 'OpenAI compatible',
  'OpenAI官方': 'OpenAI official',
  'OpenAI 官方': 'OpenAI official',
  'DeepSeek官方': 'DeepSeek official',
  'DeepSeek 官方': 'DeepSeek official',
  '通义千问': 'Qwen',
  'Kimi（月之暗面）': 'Kimi',
  '智谱GLM': 'Zhipu GLM',
  '智谱 GLM': 'Zhipu GLM',
  'MiniMax官方': 'MiniMax official',
  'MiniMax 官方': 'MiniMax official',
  'Ollama本地': 'Local Ollama',
  'Ollama 本地': 'Local Ollama',
  '硅基流动': 'SiliconFlow',
  '本地模拟分析': 'Local mock analysis',
  '备用通道B': 'Backup channel B',
  '备用通道 B': 'Backup channel B',
  '备用通道C': 'Backup channel C',
  '备用通道 C': 'Backup channel C',
  '均线交叉': 'MA Cross',
  '超买超卖回归': 'RSI Mean Reversion',
  '网格策略': 'Grid Trading',
  '突破策略': 'Breakout',
  '智能风险过滤': 'AI Risk Filter',
  '手动操作': 'Manual',
  '系统': 'System',
  '数据': 'Data',
  '新闻': 'News',
  '接口': 'API',
  '标识': 'ID',
  '接口协议': 'API format',
  '接口密钥': 'API key',
  '是否启用': 'Enabled',
  '公共行情数据': 'Public market data',
  'MySQL地址': 'MySQL host',
  'MySQL 地址': 'MySQL host',
  '数据存储方式': 'Repository backend',
  '默认交易所': 'Default exchange',
  '默认币种': 'Default symbol',
  '默认周期': 'Default timeframe',
  '公共交易所行情': 'Public exchange data',
  '新闻源数量': 'News feed count',
  '新闻缓存时间': 'News cache TTL',
  '最大数据延迟': 'Max data latency',
  '飞书通知': 'Feishu notification',
  '企业微信通知': 'WeCom notification',
  'Telegram通知': 'Telegram notification',
  'Telegram 通知': 'Telegram notification',
  '邮箱通知': 'Email notification',
  'Slack通知': 'Slack notification',
  'Slack 通知': 'Slack notification',
  'Discord通知': 'Discord notification',
  'Discord 通知': 'Discord notification',
  '提醒级别': 'Severity',
  '快线周期': 'Fast window',
  '慢线周期': 'Slow window',
  '最大仓位占比': 'Max position percent',
  '止损比例': 'Stop loss percent',
  '止盈比例': 'Take profit percent',
  '低于该值买入': 'Buy below',
  '高于该值卖出': 'Sell above',
  '网格下边界': 'Grid lower bound',
  '网格上边界': 'Grid upper bound',
  '网格数量': 'Grid count',
  '单格资金占比': 'Order size percent',
  '回看周期': 'Lookback',
  '成交量放大倍数': 'Volume multiplier',
  '要求结构化内容': 'Requires structured output',
  '不能直接下单': 'Cannot place orders',
  '重大事件风险': 'Event risk',
  '新闻数量': 'Article count',
  '来源数量': 'Source count',
  '主要标题': 'Top headlines',
  '标准差倍数': 'Deviation multiplier',
  '中轨止盈': 'Exit on middle band',
  '信号线周期': 'Signal window',
  '短均线周期': 'Short MA window',
  '长均线周期': 'Long MA window',
  '定投间隔K线': 'DCA interval candles',
  '定投间隔 K 线': 'DCA interval candles',
  '最高资金费率': 'Max funding rate',
  '合约溢价阈值': 'Premium threshold',
  '回看小时数': 'Lookback hours',
  '实时公共行情': 'Live public data',
  '本地缓存行情': 'Local cached data',
  '本地缓存为空': 'Local cache empty',
  '暂无行情数据': 'No market data',
  '交易所异常，稍后重试': 'Exchange error, retry later',
  '数据状态未知': 'Unknown data status',
  '趋势跟随': 'Trend following',
  '均值回归': 'Mean reversion',
  '震荡网格': 'Range grid',
  '风险过滤': 'Risk filter',
  '分批建仓': 'Position building',
  '自定义': 'Custom',
  '· 自定义': '· Custom',
  '现货实盘': 'Spot live',
  '现货模拟': 'Spot dry-run',
  '现货': 'Spot',
  '实盘': 'Live',
  '1 分钟': '1 minute',
  '5 分钟': '5 minutes',
  '15 分钟': '15 minutes',
  '1 小时': '1 hour',
  '4 小时': '4 hours',
  '1 天': '1 day',
  '是': 'Yes',
  '否': 'No',
  '已配置，留空则保留现有Key': 'Configured; leave blank to keep saved key',
  '已配置，留空则保留现有 Key': 'Configured; leave blank to keep saved key',
  '填写APIKey': 'Enter API key',
  '填写 API Key': 'Enter API key',
  '本地Ollama可留空': 'Local Ollama can be blank',
  '本地 Ollama 可留空': 'Local Ollama can be blank',
  '保存前可先测试当前服务商、BaseURL、APIKey、模型和接口协议是否可用。':
    'Before saving, test whether provider, Base URL, API key, model, and API format are available.',
  '保存前可先测试当前服务商、Base URL、API Key、模型和接口协议是否可用。':
    'Before saving, test whether provider, Base URL, API key, model, and API format are available.',
  '保存前可先测试当前APIKey、Secret、Passphrase、沙盒环境和只读余额权限是否可用。':
    'Before saving, test API key, secret, passphrase, sandbox, and read-only balance permission.',
  '保存前可先测试当前 API Key、Secret、Passphrase、沙盒环境和只读余额权限是否可用。':
    'Before saving, test API key, secret, passphrase, sandbox, and read-only balance permission.',
  '注意及以上': 'Warning and above',
  '低于高风险': 'Below high risk',
  '来自资产记录': 'From portfolio records',
  '暂无已实现盈亏来源': 'No realized PnL source',
  '暂无权益历史': 'No equity history',
  '已启用公共现货行情，未配置私有接口': 'Public spot market data enabled; private API not configured',
  '未配置现货接口': 'Spot API not configured',
  '这段历史行情本地已经有了': 'Historical candles are already available locally',
  '历史行情已同步到本地数据库': 'Historical candles synced into the local database',
  '同步历史行情需要先启用 MySQL 数据库': 'Historical sync requires enabling MySQL first',
  '本地没有这段历史 K 线，请先同步历史数据。':
    'Local historical candles are unavailable. Sync historical data first.',
  '均线交叉策略要求快线周期大于 0，并且小于慢线周期。':
    'MA Cross requires fast window above 0 and below slow window.',
  '网格策略回测完成，已按现货只做多固定份额规则执行。':
    'Grid Trading completed with spot long-only fixed-lot rules.',
  '突破策略回测完成，已按现货只做多规则执行。':
    'Breakout completed with spot long-only rules.',
  '布林带回归回测完成，已按现货只做多规则执行。':
    'Bollinger Bands completed with spot long-only rules.',
  'MACD 趋势回测完成，已按现货只做多规则执行。':
    'MACD Trend completed with spot long-only rules.',
  '趋势回踩回测完成，已按现货只做多规则执行。':
    'Trend Pullback completed with spot long-only rules.',
  '定投建仓回测完成，已按固定间隔现货买入规则执行。':
    'DCA completed with fixed-interval spot long-only rules.',
  '网格策略至少需要 2 根 K 线。': 'Grid Trading requires at least 2 candles.',
  '未配置AI模型通道，也没有可用的增强行情上下文。':
    'No AI channel or enriched market context is configured.',
  '未配置 AI 模型通道，也没有可用的增强行情上下文。':
    'No AI channel or enriched market context is configured.',
  '新闻情绪已关闭。': 'News sentiment is disabled.',
  '还没有配置新闻 RSS 源。': 'No news RSS feeds configured.',
  '已使用本地新闻情绪规则完成分析。': 'News sentiment context analyzed locally.',
  'AI分析结构化结果校验通过。': 'AI structured payload validation passed.',
  'AI 分析结构化结果校验通过。': 'AI structured payload validation passed.',
  'Right Code 返回了可用的结构化结果。': 'Right Code returned valid structured output.',
  'OpenAI 兼容通道返回了可用的结构化结果。': 'OpenAI-compatible channel returned valid structured output.',
  'OpenAI 返回了可用的结构化结果。': 'OpenAI returned valid structured output.',
  'DeepSeek 官方返回了可用的结构化结果。': 'DeepSeek official returned valid structured output.',
  '通义千问返回了可用的结构化结果。': 'Qwen returned valid structured output.',
  'Kimi 返回了可用的结构化结果。': 'Kimi returned valid structured output.',
  '智谱 GLM 返回了可用的结构化结果。': 'Zhipu GLM returned valid structured output.',
  'MiniMax 返回了可用的结构化结果。': 'MiniMax returned valid structured output.',
  'Ollama 本地模型返回了可用的结构化结果。': 'Local Ollama model returned valid structured output.',
  '通知已发送': 'Notification sent',
  '还没有配置飞书通知地址': 'Feishu notification URL is not configured',
  '还没有配置企业微信通知地址': 'WeCom notification URL is not configured',
  '还没有配置 Telegram Bot Token 和 Chat ID': 'Telegram Bot Token and Chat ID are not configured',
  '还没有配置邮箱 SMTP、发件人和收件人': 'Email SMTP, sender, and recipient are not configured',
  '还没有配置邮箱 SMTP 地址': 'Email SMTP host is not configured',
  '还没有配置邮箱发件人': 'Email sender is not configured',
  '还没有配置邮箱收件人': 'Email recipient is not configured',
  '还没有配置 Slack 通知地址': 'Slack notification URL is not configured',
  '还没有配置 Discord 通知地址': 'Discord notification URL is not configured',
  '结束日期必须晚于开始日期': 'End date must be after start date',
  'N/A': 'N/A',
}

const patternTranslations: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  [/^(.+) - (.+)$/, (match) => `${translateKnownText(match[1])} - ${translateKnownText(match[2])}`],
  [/^(.+) · 自定义$/, (match) => `${match[1]} · Custom`],
  [/^(.+) 通道$/, (match) => `Channel ${match[1]}`],
  [/^(.+) 详情$/, (match) => `${translateKnownText(match[1])} Details`],
  [/^风控触发暂停：(.+) 仅允许人工检查和管理已有现货仓位。$/, (match) =>
    `Risk triggered a pause: ${translateKnownText(match[1])} Manual review and existing spot position management only.`],
  [/^风控触发暂停：(.+)$/, (match) => `Risk triggered a pause: ${translateKnownText(match[1])}`],
  [/^(.+) (\d+(?:\.\d+)?) 毫秒$/, (match) => `${translateKnownText(match[1])} ${match[2]} ms`],
  [/^行情更新 (\d+) 秒前$/, (match) => `Market updated ${match[1]}s ago`],
  [/^延迟 (\d+(?:\.\d+)?) 秒$/, (match) => `${match[1]}s latency`],
  [/^置信度 (.+)$/, (match) => `Confidence ${match[1]}`],
  [/^(.+) 至 (.+)$/, (match) => `${match[1]} to ${match[2]}`],
  [/^正在加载 (.+) 行情数据$/, (match) => `Loading ${translateKnownText(match[1])} market data`],
  [/^正在读取 (.+) AI建议信号$/, (match) => `Loading ${translateKnownText(match[1])} AI decision signal`],
  [/^正在读取 (.+) AI 建议信号$/, (match) => `Loading ${translateKnownText(match[1])} AI decision signal`],
  [/^(.+) 暂无 (.+) (.+) K 线数据$/, (match) => `${translateKnownText(match[1])} has no ${match[2]} ${translateKnownText(match[3])} candles`],
  [/^(.+) \/ (.+) \/ (.+) \/ (\d+) 根 K 线$/, (match) => `${match[1]} / ${translateKnownText(match[2])} / ${translateKnownText(match[3])} / ${match[4]} candles`],
  [/^(\d+) 根$/, (match) => `${match[1]} candles`],
  [/^(\d+) 根 K 线$/, (match) => `${match[1]} candles`],
  [/^(\d+) 条记录$/, (match) => `${match[1]} records`],
  [/^(\d+) 条日志$/, (match) => `${match[1]} logs`],
  [/^(\d+) 条信号$/, (match) => `${match[1]} signals`],
  [/^共 (\d+) 条信号$/, (match) => `${match[1]} signals total`],
  [/^(\d+) 项需关注$/, (match) => `${match[1]} need attention`],
  [/^(\d+) 个$/, (match) => `${match[1]} items`],
  [/^(\d+) 个来源$/, (match) => `${match[1]} sources`],
  [/^(\d+) 个资产$/, (match) => `${match[1]} assets`],
  [/^(\d+) 条余额记录$/, (match) => `${match[1]} balance records`],
  [/^(\d+) 笔模拟成交$/, (match) => `${match[1]} simulated fills`],
  [/^(\d+) 笔交易$/, (match) => `${match[1]} trades`],
  [/^(\d+)\/(\d+) 接口$/, (match) => `${match[1]}/${match[2]} APIs`],
  [/^(\d+)\/(\d+) 现货启用$/, (match) => `${match[1]}/${match[2]} spot enabled`],
  [/^(\d+)\/(\d+) 启用$/, (match) => `${match[1]}/${match[2]} enabled`],
  [/^(\d+)\/(\d+) 有值$/, (match) => `${match[1]}/${match[2]} set`],
  [/^(\d+)\/(\d+) 已配置$/, (match) => `${match[1]}/${match[2]} configured`],
  [/^(\d+)\/(\d+) 已绑定$/, (match) => `${match[1]}/${match[2]} bound`],
  [/^(\d+)\/(\d+) 必填$/, (match) => `${match[1]}/${match[2]} required`],
  [/^(\d+)\/(\d+) 通过$/, (match) => `${match[1]}/${match[2]} passed`],
  [/^(\d+)\/(\d+) 类可用$/, (match) => `${match[1]}/${match[2]} categories ready`],
  [/^拉取 (\d+) 根 \/ 新增 (\d+) 根 \/ 更新 (\d+) 根$/, (match) => `Fetched ${match[1]} / inserted ${match[2]} / updated ${match[3]} candles`],
  [/^(.+) 已加入自定义币种$/, (match) => `${match[1]} added to custom symbols`],
  [/^将添加 (.+)$/, (match) => `Will add ${match[1]}`],
  [/^(.+) 已是内置币种$/, (match) => `${match[1]} is already built in`],
  [/^(.+) 已(.+)$/, (match) => `${translateKnownText(match[1])} ${translateKnownText(match[2])}`],
  [/^(.+) 模式已更新$/, (match) => `${translateKnownText(match[1])} mode updated`],
  [/^Signal Engine 已生成 (\d+) 条信号$/, (match) => `Signal Engine generated ${match[1]} signals`],
  [/^当前策略(.+)，不能运行回测$/, (match) => `The selected strategy is ${translateKnownText(match[1])} and cannot be backtested`],
  [/^(.+) 开启现货交易前需要先配置完整 API Key$/, (match) => `${translateKnownText(match[1])} needs full API credentials before enabling spot trading`],
  [/^(.+) 需要完整 API Key 后才能测试$/, (match) => `${translateKnownText(match[1])} needs full API credentials before testing`],
  [/^已配置，留空则保留现有 (.+)$/, (match) => `Configured; leave blank to keep saved ${match[1]}`],
  [/^填写 (.+)$/, (match) => `Enter ${match[1]}`],
  [/^(.+)通知测试结果：(.+)$/, (match) => `${translateKnownText(match[1])} notification test result: ${translateKnownText(match[2])}`],
  [/^(.+)：(.+)$/, (match) => `${translateKnownText(match[1])}: ${translateKnownText(match[2])}`],
  [/^(.+)，(.+)$/, (match) => `${translateKnownText(match[1])}, ${translateKnownText(match[2])}`],
  [/^(.+)。(.+)$/, (match) => `${translateKnownText(match[1])}. ${translateKnownText(match[2])}`],
  [/^(\d+) 秒 \/ (.+)$/, (match) => `${match[1]}s / ${translateKnownText(match[2])}`],
  [/^<= (\d+) 秒且数据完整$/, (match) => `<= ${match[1]}s and complete`],
  [/^(.+) 条 \/ (.+) 个来源$/, (match) => `${match[1]} articles / ${match[2]} sources`],
]
