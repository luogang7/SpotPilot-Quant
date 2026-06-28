<script setup lang="ts">
import { computed, ref } from 'vue'

import { api } from '../../shared/api/client'
import { formatDateTime, formatMessage, formatModule, formatStatus, formatStrategyName } from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'

const activeFilter = ref('全部')
const filters = [
  { label: '全部', modules: [] },
  { label: '策略', modules: ['strategy', 'backtest'] },
  { label: '智能分析', modules: ['ai'] },
  { label: '风控', modules: ['risk'] },
  { label: '交易', modules: ['trading'] },
  { label: '数据', modules: ['data', 'market'] },
  { label: '接口错误', modules: ['api', 'api_error'] },
]
const { data, loading, error, refresh } = useResource(() => api.getLogs(50))

const visibleLogs = computed(() => {
  const logs = data.value ?? []
  if (activeFilter.value === '全部') {
    return logs
  }
  const activeModules = filters.find((filter) => filter.label === activeFilter.value)?.modules ?? []
  return logs.filter((log) => activeModules.includes(log.module))
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">日志</h1>
        <p class="page-subtitle">记录策略、智能分析、风控、交易、数据和接口错误，保证每次决策可追溯。</p>
      </div>
      <button type="button" class="ghost-button" @click="refresh">刷新</button>
    </header>

    <div class="toolbar-row">
      <button
        v-for="filter in filters"
        :key="filter.label"
        type="button"
        class="compact-button"
        :class="{ active: activeFilter === filter.label }"
        @click="activeFilter = filter.label"
      >
        {{ filter.label }}
      </button>
    </div>

    <EmptyState v-if="loading" state="loading" message="正在加载日志" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <SectionPanel v-else title="日志列表" :note="`${visibleLogs.length} 条记录`">
      <EmptyState v-if="visibleLogs.length === 0" state="empty" message="当前筛选没有日志" />
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>级别</th>
            <th>模块</th>
            <th>币种</th>
            <th>策略</th>
            <th>消息</th>
            <th>关联编号</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in visibleLogs" :key="log.correlation_id">
            <td>{{ formatDateTime(log.occurred_at) }}</td>
            <td><StatusBadge :label="formatStatus(log.level)" :tone="log.level" /></td>
            <td>{{ formatModule(log.module) }}</td>
            <td>{{ log.symbol ?? '-' }}</td>
            <td>{{ log.strategy ? formatStrategyName(log.strategy) : '-' }}</td>
            <td>{{ formatMessage(log.message) }}</td>
            <td>{{ log.correlation_id }}</td>
          </tr>
        </tbody>
      </table>
    </SectionPanel>
  </div>
</template>
