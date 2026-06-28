<script setup lang="ts">
import { computed, ref } from 'vue'

import { api } from '../../shared/api/client'
import {
  formatAction,
  formatCodeValue,
  formatDateTime,
  formatMarketRegime,
  formatMessage,
  formatModule,
  formatMoney,
  formatProvider,
  formatRiskLevel,
  formatStatus,
  formatStrategyName,
} from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'

const forceRefresh = ref(false)

const { data, loading, error, refresh } = useResource(() => api.getDashboard({
  refresh: forceRefresh.value || undefined,
}))

async function refreshDashboard() {
  forceRefresh.value = true
  try {
    await refresh()
  } finally {
    forceRefresh.value = false
  }
}

const equityPoints = computed(() => {
  const values = data.value?.equity_curve ?? []
  if (values.length === 0) {
    return ''
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, 1)
  return values
    .map((value, index) => {
      const x = 18 + (index * 460) / Math.max(values.length - 1, 1)
      const y = 200 - ((value - min) / spread) * 160
      return `${x},${y}`
    })
    .join(' ')
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">总览</h1>
        <p class="page-subtitle">集中查看资产、现货持仓、策略信号、AI判断、风控状态和最新日志。</p>
      </div>
      <div class="page-actions">
        <button type="button" class="ghost-button" @click="refreshDashboard">刷新</button>
      </div>
    </header>

    <EmptyState v-if="loading" state="loading" message="正在加载系统总览" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <template v-else-if="data">
      <div class="grid metrics">
        <MetricCard
          v-for="metric in data.metrics"
          :key="metric.label"
          :label="metric.label"
          :value="formatCodeValue(metric.value)"
          :detail="formatMessage(metric.detail)"
          :severity="metric.severity"
        />
      </div>

      <div class="grid two">
        <SectionPanel title="资产曲线 / 收益曲线" note="模拟运行账户权益">
          <div class="panel-body">
            <div class="chart-box">
              <svg viewBox="0 0 500 230" role="img" aria-label="资产曲线">
                <polyline
                  :points="equityPoints"
                  fill="none"
                  stroke="#40d7d0"
                  stroke-width="3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <line class="chart-axis-line" x1="18" y1="200" x2="480" y2="200" />
              </svg>
            </div>
          </div>
        </SectionPanel>

        <SectionPanel title="当前现货持仓" note="只展示已有现货">
          <table class="data-table">
            <thead>
              <tr>
                <th>币种</th>
                <th>数量</th>
                <th>均价</th>
                <th>浮盈</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="position in data.positions" :key="position.symbol">
                <td>{{ position.symbol }}</td>
                <td>{{ position.quantity }}</td>
                <td>{{ formatMoney(position.average_price, 0) }}</td>
                <td class="positive">{{ formatMoney(position.unrealized_pnl) }}</td>
              </tr>
            </tbody>
          </table>
        </SectionPanel>
      </div>

      <div class="grid two">
        <SectionPanel title="最新策略信号" note="AI分析 / 风控拦截可追踪">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>币种</th>
                <th>策略</th>
                <th>动作</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="signal in data.latest_signals" :key="signal.correlation_id">
                <td>{{ formatDateTime(signal.occurred_at) }}</td>
                <td>{{ signal.symbol }}</td>
                <td>{{ formatStrategyName(signal.strategy) }}</td>
                <td><StatusBadge :label="formatAction(signal.action)" :tone="signal.blocked_by ? 'warning' : 'success'" /></td>
                <td>{{ signal.blocked_by ? formatCodeValue(signal.blocked_by) : formatMessage(signal.reason) }}</td>
              </tr>
            </tbody>
          </table>
        </SectionPanel>

        <SectionPanel title="AI市场判断" :note="`${formatProvider(data.ai.provider)} / ${data.ai.model}`">
          <div class="grid three panel-body">
            <MetricCard label="市场状态" :value="formatMarketRegime(data.ai.market_regime)" detail="结构化输出" />
            <MetricCard label="风险等级" :value="formatRiskLevel(data.ai.risk_level)" :detail="`置信度 ${data.ai.confidence}`" severity="warning" />
            <MetricCard label="允许方向" :value="formatAction(data.ai.allowed_direction)" detail="AI分析不直接下单" />
          </div>
        </SectionPanel>
      </div>

      <SectionPanel title="最新日志" note="审计链路">
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>级别</th>
              <th>模块</th>
              <th>消息</th>
              <th>关联编号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in data.latest_logs" :key="log.correlation_id">
              <td>{{ formatDateTime(log.occurred_at) }}</td>
              <td><StatusBadge :label="formatStatus(log.level)" :tone="log.level" /></td>
              <td>{{ formatModule(log.module) }}</td>
              <td>{{ formatMessage(log.message) }}</td>
              <td>{{ log.correlation_id }}</td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>
    </template>
  </div>
</template>
