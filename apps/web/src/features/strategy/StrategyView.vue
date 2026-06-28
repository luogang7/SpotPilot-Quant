<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import { api } from '../../shared/api/client'
import {
  formatAction,
  formatBoolean,
  formatCodeValue,
  formatDateTime,
  formatFieldName,
  formatMessage,
  formatMoney,
  formatStatus,
  formatStrategyName,
  formatTradingMode,
} from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import type { StrategyConfig, StrategyUpdateRequest } from '../../shared/types/workbench'

type StrategyScalar = StrategyConfig['parameters'][string]
type StrategyValueGroup = 'parameters' | 'risk_controls'

const selectedId = ref('ma_cross')
const { data, loading, error, refresh } = useResource(api.getStrategies)
const saving = ref(false)
const savingId = ref<string | null>(null)
const scanning = ref(false)
const saveMessage = ref('')
const parameterDraft = ref<Record<string, StrategyScalar>>({})
const riskControlDraft = ref<Record<string, StrategyScalar>>({})
const modeOptions = [
  { value: 'dry_run', label: '模拟运行' },
  { value: 'backtest_only', label: '仅回测' },
  { value: 'risk_filter', label: '风控过滤' },
]

const selectedStrategy = computed(() => {
  const strategies = data.value ?? []
  return strategies.find((strategy) => strategy.id === selectedId.value) ?? strategies[0]
})

const selectedSupportsSignals = computed(() => selectedStrategy.value?.supports_signals === true)
const selectedSupportsBacktest = computed(() => selectedStrategy.value?.supports_backtest === true)

const strategyStats = computed(() => {
  const strategies = data.value ?? []
  return {
    total: strategies.length,
    enabled: strategies.filter((strategy) => strategy.enabled).length,
    signal: strategies.filter((strategy) => strategy.supports_signals).length,
    backtest: strategies.filter((strategy) => strategy.supports_backtest).length,
  }
})

const hasDraftChanges = computed(() => {
  const strategy = selectedStrategy.value
  if (!strategy) {
    return false
  }
  return (
    JSON.stringify(parameterDraft.value) !== JSON.stringify(strategy.parameters) ||
    JSON.stringify(riskControlDraft.value) !== JSON.stringify(strategy.risk_controls)
  )
})

watch(
  selectedStrategy,
  (strategy) => {
    parameterDraft.value = { ...(strategy?.parameters ?? {}) }
    riskControlDraft.value = { ...(strategy?.risk_controls ?? {}) }
  },
  { immediate: true },
)

function replaceStrategy(updatedStrategy: StrategyConfig) {
  if (!data.value) {
    return
  }
  data.value = data.value.map((strategy) =>
    strategy.id === updatedStrategy.id ? updatedStrategy : strategy,
  )
}

async function persistStrategy(strategy: StrategyConfig, patch: StrategyUpdateRequest, message: string) {
  savingId.value = strategy.id
  saveMessage.value = ''
  try {
    const updatedStrategy = await api.updateStrategy(strategy.id, {
      enabled: patch.enabled ?? strategy.enabled,
      mode: patch.mode ?? strategy.mode,
      parameters: patch.parameters ?? strategy.parameters,
      risk_controls: patch.risk_controls ?? strategy.risk_controls,
    })
    replaceStrategy(updatedStrategy)
    saveMessage.value = message
    await refresh({ silent: true })
  } catch (err) {
    saveMessage.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    savingId.value = null
  }
}

async function toggleStrategy(strategy: StrategyConfig) {
  await persistStrategy(
    strategy,
    { enabled: !strategy.enabled },
    `${formatStrategyName(strategy.name)} 已${strategy.enabled ? '停用' : '启用'}`,
  )
}

async function setStrategyMode(strategy: StrategyConfig, mode: string) {
  if (strategy.mode === mode) {
    return
  }
  await persistStrategy(strategy, { mode }, `${formatStrategyName(strategy.name)} 模式已更新`)
}

async function saveStrategy() {
  if (!selectedStrategy.value) {
    return
  }
  saving.value = true
  saveMessage.value = ''
  try {
    savingId.value = selectedStrategy.value.id
    const updatedStrategy = await api.updateStrategy(selectedStrategy.value.id, {
      enabled: selectedStrategy.value.enabled,
      mode: selectedStrategy.value.mode,
      parameters: parameterDraft.value,
      risk_controls: riskControlDraft.value,
    })
    replaceStrategy(updatedStrategy)
    saveMessage.value = '保存完成'
    await refresh({ silent: true })
  } catch (err) {
    saveMessage.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    saving.value = false
    savingId.value = null
  }
}

async function runSignalEngine() {
  scanning.value = true
  saveMessage.value = ''
  try {
    const signals = await api.runStrategySignals()
    saveMessage.value = `Signal Engine 已生成 ${signals.length} 条信号`
    await refresh({ silent: true })
  } catch (err) {
    saveMessage.value = err instanceof Error ? err.message : '信号生成失败'
  } finally {
    scanning.value = false
  }
}

function strategyHelpText(strategy: StrategyConfig) {
  const description = formatMessage(strategy.description || '暂无策略说明')
  const family = formatStatus(strategy.family ?? 'custom')
  const capabilities = [
    strategy.supports_signals ? '支持信号生成' : '不生成信号',
    strategy.supports_backtest ? '支持回测' : '不参与回测',
    strategy.supports_live ? '可进入实盘链路' : '不直接实盘',
  ].join(' / ')

  return `${formatStrategyName(strategy.name)}：${description} 类型：${family}。能力：${capabilities}。`
}

function updateDraft(group: StrategyValueGroup, key: string, value: StrategyScalar) {
  const draft = group === 'parameters' ? parameterDraft : riskControlDraft
  draft.value = {
    ...draft.value,
    [key]: value,
  }
}

function updateNumberDraft(group: StrategyValueGroup, key: string, event: Event) {
  const input = event.target as HTMLInputElement
  updateDraft(group, key, Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : 0)
}

function updateTextDraft(group: StrategyValueGroup, key: string, event: Event) {
  updateDraft(group, key, (event.target as HTMLInputElement).value)
}

function updateBooleanDraft(group: StrategyValueGroup, key: string, event: Event) {
  updateDraft(group, key, (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">策略实验室</h1>
        <p class="page-subtitle">策略管理中心统一注册趋势、回归、网格、突破、定投和风控过滤节点，并把信号交给后续风控链路。</p>
      </div>
      <div class="page-actions">
        <button type="button" class="ghost-button" @click="refresh">刷新</button>
        <button type="button" class="ghost-button" :disabled="scanning" @click="runSignalEngine">
          {{ scanning ? '生成中' : '生成策略信号' }}
        </button>
        <span v-if="saveMessage" class="inline-status">{{ saveMessage }}</span>
        <button type="button" class="primary-button" :disabled="saving || !hasDraftChanges" @click="saveStrategy">
          {{ saving ? '保存中' : '保存策略参数' }}
        </button>
      </div>
    </header>

    <EmptyState v-if="loading && !data" state="loading" message="正在加载策略列表" />
    <EmptyState v-else-if="error && !data" state="error" :message="error" />

    <template v-else-if="data && selectedStrategy">
      <div class="grid metrics strategy-metrics">
        <div class="metric-card">
          <span>注册策略</span>
          <strong>{{ strategyStats.total }}</strong>
        </div>
        <div class="metric-card success">
          <span>已启用</span>
          <strong>{{ strategyStats.enabled }}</strong>
        </div>
        <div class="metric-card">
          <span>信号策略</span>
          <strong>{{ strategyStats.signal }}</strong>
        </div>
        <div class="metric-card">
          <span>可回测</span>
          <strong>{{ strategyStats.backtest }}</strong>
        </div>
      </div>

      <div class="grid two">
        <SectionPanel title="策略管理中心" note="统一注册表">
          <div class="strategy-list">
            <div
              v-for="strategy in data"
              :key="strategy.id"
              class="strategy-row"
              :class="{ active: selectedStrategy.id === strategy.id }"
            >
              <button type="button" class="strategy-select" @click="selectedId = strategy.id">
                <span class="strategy-title-line">
                  <strong>{{ formatStrategyName(strategy.name) }}</strong>
                  <span class="strategy-help" :data-tooltip="strategyHelpText(strategy)">
                    <CircleHelp
                      aria-hidden="true"
                      :size="16"
                      :stroke-width="2"
                    />
                  </span>
                </span>
                <small>
                  {{ formatStatus(strategy.family ?? 'custom') }} · {{ formatTradingMode(strategy.mode) }} · {{ formatStatus(strategy.status) }}
                </small>
              </button>
              <button
                type="button"
                class="status-toggle"
                :class="{ active: strategy.enabled }"
                :aria-pressed="strategy.enabled"
                :disabled="savingId === strategy.id"
                @click.stop="toggleStrategy(strategy)"
              >
                <span class="status-dot"></span>
                {{ savingId === strategy.id ? '保存中' : strategy.enabled ? '启用' : '停用' }}
              </button>
            </div>
          </div>
        </SectionPanel>

        <SectionPanel :title="`${formatStrategyName(selectedStrategy.name)} 详情`" note="只产生现货信号">
          <div class="panel-body grid">
            <p v-if="selectedStrategy.description" class="strategy-description">
              {{ formatMessage(selectedStrategy.description) }}
            </p>
            <div class="strategy-controls">
              <button
                type="button"
                class="status-toggle"
                :class="{ active: selectedStrategy.enabled }"
                :aria-pressed="selectedStrategy.enabled"
                :disabled="savingId === selectedStrategy.id"
                @click="toggleStrategy(selectedStrategy)"
              >
                <span class="status-dot"></span>
                {{ selectedStrategy.enabled ? '启用' : '停用' }}
              </button>
              <div class="segmented-control" aria-label="策略模式">
                <button
                  v-for="option in modeOptions"
                  :key="option.value"
                  type="button"
                  :class="{ active: selectedStrategy.mode === option.value }"
                  :disabled="savingId === selectedStrategy.id"
                  @click="setStrategyMode(selectedStrategy, option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
              <StatusBadge label="禁止开空 / 加杠杆" tone="success" />
              <StatusBadge
                :label="selectedSupportsSignals ? 'Signal Engine' : '无信号输出'"
                :tone="selectedSupportsSignals ? 'success' : 'warning'"
              />
              <StatusBadge
                :label="selectedSupportsBacktest ? 'Backtest Engine' : '不可回测'"
                :tone="selectedSupportsBacktest ? 'success' : 'warning'"
              />
            </div>

            <table class="data-table">
              <thead>
                <tr>
                  <th>参数</th>
                  <th>值</th>
                  <th>类型</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(value, key) in parameterDraft" :key="key">
                  <td>{{ formatFieldName(key) }}</td>
                  <td>
                    <input
                      v-if="typeof value === 'number'"
                      class="table-input"
                      type="number"
                      step="any"
                      :value="value"
                      @input="updateNumberDraft('parameters', String(key), $event)"
                    />
                    <label v-else-if="typeof value === 'boolean'" class="table-checkbox">
                      <input
                        type="checkbox"
                        :checked="value"
                        @change="updateBooleanDraft('parameters', String(key), $event)"
                      />
                      <span>{{ formatBoolean(value) }}</span>
                    </label>
                    <input
                      v-else
                      class="table-input"
                      type="text"
                      :value="value"
                      @input="updateTextDraft('parameters', String(key), $event)"
                    />
                  </td>
                  <td>策略参数</td>
                </tr>
                <tr v-for="(value, key) in riskControlDraft" :key="key">
                  <td>{{ formatFieldName(key) }}</td>
                  <td>
                    <input
                      v-if="typeof value === 'number'"
                      class="table-input"
                      type="number"
                      step="any"
                      :value="value"
                      @input="updateNumberDraft('risk_controls', String(key), $event)"
                    />
                    <label v-else-if="typeof value === 'boolean'" class="table-checkbox">
                      <input
                        type="checkbox"
                        :checked="value"
                        @change="updateBooleanDraft('risk_controls', String(key), $event)"
                      />
                      <span>{{ formatBoolean(value) }}</span>
                    </label>
                    <input
                      v-else
                      class="table-input"
                      type="text"
                      :value="value"
                      @input="updateTextDraft('risk_controls', String(key), $event)"
                    />
                  </td>
                  <td>风控参数</td>
                </tr>
              </tbody>
            </table>
          </div>
        </SectionPanel>
      </div>

      <SectionPanel title="最近信号" note="展示是否被AI分析 / 风控拦截">
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>币种</th>
              <th>策略</th>
              <th>动作</th>
              <th>价格</th>
              <th>原因 / 拦截</th>
              <th>关联编号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="signal in selectedStrategy.recent_signals" :key="signal.correlation_id">
              <td>{{ formatDateTime(signal.occurred_at) }}</td>
              <td>{{ signal.symbol }}</td>
              <td>{{ formatStrategyName(signal.strategy) }}</td>
              <td><StatusBadge :label="formatAction(signal.action)" :tone="signal.blocked_by ? 'warning' : 'success'" /></td>
              <td>{{ formatMoney(signal.price, 0) }}</td>
              <td>{{ signal.blocked_by ? formatCodeValue(signal.blocked_by) : formatMessage(signal.reason) }}</td>
              <td>{{ signal.correlation_id }}</td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>
    </template>
  </div>
</template>
