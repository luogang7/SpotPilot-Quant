<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import { computed } from 'vue'

import { api } from '../../shared/api/client'
import { formatCodeValue, formatDateTime, formatMessage, formatRuleText, formatStatus } from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import type { Severity } from '../../shared/types/workbench'

const { data, loading, error, refresh } = useResource(api.getRiskStatus)

const riskTone = computed<Severity>(() => {
  if (data.value?.status === 'allow_trading') {
    return 'success'
  }
  if (data.value?.status === 'paused') {
    return 'critical'
  }
  return 'warning'
})
const activeBlocks = computed(() => data.value?.rules.filter((rule) => rule.action !== 'allow').length ?? 0)
const warningRules = computed(() => data.value?.rules.filter((rule) => rule.status !== 'success').length ?? 0)

function actionTone(action: string): Severity {
  if (action === 'allow') {
    return 'success'
  }
  if (['pause_all', 'kill_switch', 'blocked', 'stop'].includes(action)) {
    return 'critical'
  }
  return 'warning'
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">风控中心</h1>
        <p class="page-subtitle">管理单笔亏损、单日亏损、最大回撤、仓位上限、连续亏损暂停和AI分析高风险暂停。</p>
      </div>
      <div class="page-actions">
        <button type="button" class="ghost-button" :disabled="loading" @click="refresh">
          <RefreshCw :size="15" />
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </header>

    <EmptyState v-if="loading" state="loading" message="正在加载风控状态" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <template v-else-if="data">
      <div class="grid metrics risk-metrics">
        <MetricCard label="当前状态" :value="formatStatus(data.status)" :detail="formatMessage(data.summary)" :severity="riskTone" />
        <MetricCard label="规则总数" :value="String(data.rules.length)" detail="P0 风控检查项" />
        <MetricCard label="待关注规则" :value="String(warningRules)" detail="状态非通过的规则" :severity="warningRules ? 'warning' : 'success'" />
        <MetricCard label="限制动作" :value="String(activeBlocks)" detail="禁止或降仓动作" :severity="activeBlocks ? 'warning' : 'success'" />
        <MetricCard label="审计事件" :value="String(data.events.length)" detail="风控拦截链路" />
      </div>

      <SectionPanel title="风控规则" note="当前值 / 阈值">
        <template #actions>
          <StatusBadge :label="warningRules ? `${warningRules} 项需关注` : '全部正常'" :tone="warningRules ? 'warning' : 'success'" />
        </template>
        <table class="data-table">
          <thead>
            <tr>
              <th>规则</th>
              <th>当前值</th>
              <th>阈值</th>
              <th>状态</th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in data.rules" :key="rule.name">
              <td>{{ formatStatus(rule.name) }}</td>
              <td>{{ formatRuleText(rule.current_value) }}</td>
              <td>{{ formatRuleText(rule.threshold) }}</td>
              <td><StatusBadge :label="formatStatus(rule.status)" :tone="rule.status" /></td>
              <td><StatusBadge :label="formatStatus(rule.action)" :tone="actionTone(rule.action)" /></td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>

      <SectionPanel title="风控事件" note="所有拦截必须可追溯">
        <template #actions>
          <StatusBadge label="实时审计" tone="info" />
        </template>
        <table v-if="data.events.length" class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>规则</th>
              <th>币种</th>
              <th>触发值</th>
              <th>动作</th>
              <th>原因</th>
              <th>关联编号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in data.events" :key="event.correlation_id">
              <td>{{ formatDateTime(event.occurred_at) }}</td>
              <td>{{ formatStatus(event.rule) }}</td>
              <td>{{ formatCodeValue(event.symbol) }}</td>
              <td>{{ formatRuleText(event.trigger_value) }}</td>
              <td><StatusBadge :label="formatStatus(event.action)" :tone="actionTone(event.action)" /></td>
              <td>{{ formatMessage(event.reason) }}</td>
              <td>{{ event.correlation_id }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="table-empty-message">暂无风控事件</div>
      </SectionPanel>
    </template>
  </div>
</template>
