<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { useSystemStore } from '../../app/store'
import { api } from '../../shared/api/client'
import {
  formatAction,
  formatBoolean,
  formatDateTime,
  formatExchange,
  formatMoney,
  formatStatus,
  formatTradingMode,
} from '../../shared/api/format'
import { useResource } from '../../shared/api/useResource'
import EmptyState from '../../shared/components/EmptyState.vue'
import MetricCard from '../../shared/components/MetricCard.vue'
import SectionPanel from '../../shared/components/SectionPanel.vue'
import StatusBadge from '../../shared/components/StatusBadge.vue'
import type {
  DryRunOrderRequest,
  LiveOrderRequest,
  Order,
  Severity,
  TradingMode,
} from '../../shared/types/workbench'

const { data, loading, error, refresh } = useResource(api.getTradingSummary)
const systemStore = useSystemStore()
const tradeMode = ref<TradingMode>('dry_run')
const liveExchange = ref<'binance' | 'okx'>('binance')
const orderDraft = ref<LiveOrderRequest>({
  exchange: 'binance',
  symbol: 'BTC/USDT',
  action: 'buy',
  order_type: 'market',
  quantity: 0.01,
  price: null,
  strategy: 'ma_cross',
})
const orderSubmitting = ref(false)
const orderResult = ref<Order | null>(null)
const orderError = ref('')
const controlSubmitting = ref(false)
const controlMessage = ref('')
const controlError = ref('')
const actionOptions = [
  { value: 'buy', label: '买入' },
  { value: 'sell_existing', label: '卖出现货' },
  { value: 'hold', label: '观望' },
  { value: 'cancel_order', label: '撤单' },
] as const
const liveActionOptions = actionOptions.filter((option) => option.value === 'buy' || option.value === 'sell_existing')
const selectedModeLabel = computed(() => (tradeMode.value === 'live' ? '小额实盘' : '模拟运行'))
const canSubmitLiveOrder = computed(() =>
  tradeMode.value === 'live' &&
  (orderDraft.value.action === 'buy' || orderDraft.value.action === 'sell_existing'),
)

watch(tradeMode, (mode) => {
  if (mode === 'live' && !canSubmitLiveOrder.value) {
    orderDraft.value.action = 'buy'
  }
})

async function confirmAction(title: string, detail: string) {
  try {
    await ElMessageBox.confirm(detail, title, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      autofocus: false,
      closeOnClickModal: false,
    })
    return true
  } catch {
    ElMessage.info('已取消操作')
    return false
  }
}

function selectDryRunMode() {
  tradeMode.value = 'dry_run'
  orderError.value = ''
  orderResult.value = null
}

async function requestLiveMode() {
  if (tradeMode.value === 'live') {
    return
  }

  try {
    await ElMessageBox.confirm(
      '小额实盘会向交易所发送真实现货订单。请确认合约、杠杆、保证金和提现权限均已关闭，并已完成交易所账号绑定。',
      '切换到小额实盘',
      {
        type: 'warning',
        confirmButtonText: '确认切换',
        cancelButtonText: '继续模拟',
        autofocus: false,
        closeOnClickModal: false,
      },
    )
    tradeMode.value = 'live'
    orderError.value = ''
    orderResult.value = null
    ElMessage.success('已切换到小额实盘')
  } catch {
    ElMessage.info('已保留模拟运行')
  }
}

function orderStatusTone(status: string): Severity {
  if (status.startsWith('rejected')) {
    return 'warning'
  }
  if (status.startsWith('validated')) {
    return 'success'
  }
  return 'info'
}

async function submitDryRunOrder() {
  orderSubmitting.value = true
  orderError.value = ''
  try {
    const payload: DryRunOrderRequest = {
      symbol: orderDraft.value.symbol,
      action: orderDraft.value.action,
      order_type: orderDraft.value.order_type,
      quantity: orderDraft.value.quantity,
      price: orderDraft.value.price,
      strategy: orderDraft.value.strategy,
    }
    orderResult.value = await api.createDryRunOrder(payload)
    await refresh()
  } catch (err) {
    orderError.value = err instanceof Error ? err.message : 'dry-run 订单校验失败'
  } finally {
    orderSubmitting.value = false
  }
}

async function submitLiveOrder() {
  if (!canSubmitLiveOrder.value) {
    orderError.value = '实盘只支持买入或卖出现货，请使用单独的撤单按钮'
    return
  }
  const confirmed = await confirmAction(
    '确认实盘现货下单',
    `${formatExchange(liveExchange.value)} ${formatAction(orderDraft.value.action)} ${orderDraft.value.quantity} ${orderDraft.value.symbol}`,
  )
  if (!confirmed) {
    return
  }

  orderSubmitting.value = true
  orderError.value = ''
  try {
    orderResult.value = await api.createLiveOrder({
      ...orderDraft.value,
      exchange: liveExchange.value,
    })
    await refresh()
  } catch (err) {
    orderError.value = err instanceof Error ? err.message : '实盘订单提交失败'
  } finally {
    orderSubmitting.value = false
  }
}

async function cancelOrder(order: Order) {
  const confirmed = await confirmAction(
    '确认撤销现货挂单',
    `${formatExchange(order.exchange)} ${order.symbol} / ${order.order_id}`,
  )
  if (!confirmed) {
    return
  }

  orderSubmitting.value = true
  orderError.value = ''
  try {
    orderResult.value = await api.cancelLiveOrder({
      exchange: order.exchange,
      symbol: order.symbol,
      order_id: order.order_id,
    })
    await refresh()
  } catch (err) {
    orderError.value = err instanceof Error ? err.message : '撤单失败'
  } finally {
    orderSubmitting.value = false
  }
}

async function closePosition(symbol: string, quantity: number) {
  const confirmed = await confirmAction(
    '确认手动平仓',
    `${formatExchange(liveExchange.value)} 将按市价卖出 ${quantity} ${symbol}`,
  )
  if (!confirmed) {
    return
  }

  orderSubmitting.value = true
  orderError.value = ''
  try {
    orderResult.value = await api.closeLivePosition({
      exchange: liveExchange.value,
      symbol,
      quantity,
      order_type: 'market',
    })
    await refresh()
  } catch (err) {
    orderError.value = err instanceof Error ? err.message : '手动平仓失败'
  } finally {
    orderSubmitting.value = false
  }
}

async function toggleStrategyPause() {
  controlSubmitting.value = true
  controlMessage.value = ''
  controlError.value = ''
  try {
    const nextPaused = !systemStore.paused
    await systemStore.setPaused(nextPaused, nextPaused ? 'trading_page_pause' : 'trading_page_resume')
    controlMessage.value = nextPaused ? '策略开仓已暂停' : '策略开仓已恢复'
  } catch (err) {
    controlError.value = err instanceof Error ? err.message : '系统控制状态更新失败'
  } finally {
    controlSubmitting.value = false
  }
}

async function triggerKillSwitch() {
  try {
    await ElMessageBox.confirm(
      '紧急停止会暂停自动交易并拒绝新开仓，已有现货挂单请在列表中逐笔撤销。',
      '确认触发紧急停止',
      {
        type: 'error',
        confirmButtonText: '触发紧急停止',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        autofocus: false,
        closeOnClickModal: false,
      },
    )
  } catch {
    ElMessage.info('已取消紧急停止')
    return
  }

  controlSubmitting.value = true
  controlMessage.value = ''
  controlError.value = ''
  try {
    await systemStore.setKillSwitch(true, 'trading_page_kill_switch')
    controlMessage.value = '紧急停止已触发，后端风控将拒绝新开仓'
  } catch (err) {
    controlError.value = err instanceof Error ? err.message : '紧急停止触发失败'
  } finally {
    controlSubmitting.value = false
  }
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">交易执行</h1>
        <p class="page-subtitle">第一版只允许现货模拟运行 / 小额实盘验证，禁止合约、杠杆、保证金和裸空。</p>
      </div>
      <div class="page-actions trading-page-actions">
        <div class="mode-switch" role="group" aria-label="交易运行模式">
          <button type="button" :class="{ active: tradeMode === 'dry_run' }" @click="selectDryRunMode">模拟运行</button>
          <button type="button" class="live-button" :class="{ active: tradeMode === 'live' }" @click="requestLiveMode">小额实盘</button>
        </div>
        <button type="button" class="ghost-button" @click="refresh">刷新</button>
      </div>
    </header>

    <EmptyState v-if="loading" state="loading" message="正在加载交易摘要" />
    <EmptyState v-else-if="error" state="error" :message="error" />

    <template v-else-if="data">
      <div class="grid metrics">
        <MetricCard label="模式" :value="formatTradingMode(data.mode)" detail="现货交易" :severity="data.mode === 'live' ? 'critical' : 'success'" />
        <MetricCard label="账户余额" :value="formatMoney(data.balances.reduce((sum, item) => sum + item.total, 0))" detail="来自本地资产记录" />
        <MetricCard label="当前持仓" :value="String(data.positions.length)" detail="只展示现货持仓" />
        <MetricCard label="当前挂单" :value="String(data.open_orders.length)" detail="撤单可审计" severity="warning" />
        <MetricCard label="合约禁用" :value="formatBoolean(data.contract_trading_disabled)" detail="永续 / 交割合约已禁用" severity="success" />
      </div>

      <SectionPanel title="当前现货持仓" note="卖出只允许卖出现有持仓">
        <table class="data-table">
          <thead>
            <tr>
              <th>币种</th>
              <th>方向</th>
              <th>数量</th>
              <th>均价</th>
              <th>当前价</th>
              <th>浮盈</th>
              <th>止损</th>
              <th>止盈</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="position in data.positions" :key="position.symbol">
              <td>{{ position.symbol }}</td>
              <td><StatusBadge label="现货多头" tone="success" /></td>
              <td>{{ position.quantity }}</td>
              <td>{{ formatMoney(position.average_price, 0) }}</td>
              <td>{{ formatMoney(position.current_price, 0) }}</td>
              <td class="positive">{{ formatMoney(position.unrealized_pnl) }}</td>
              <td>{{ position.stop_loss ? formatMoney(position.stop_loss, 0) : '-' }}</td>
              <td>{{ position.take_profit ? formatMoney(position.take_profit, 0) : '-' }}</td>
              <td>
                <button type="button" class="compact-button" :disabled="orderSubmitting" @click="closePosition(position.symbol, position.quantity)">平仓</button>
              </td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>

      <div class="grid two">
        <SectionPanel title="当前挂单" note="防止遗留订单">
          <table class="data-table">
            <thead>
              <tr>
                <th>订单编号</th>
                <th>交易所</th>
                <th>币种</th>
                <th>方向</th>
                <th>价格</th>
                <th>数量</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="order in data.open_orders" :key="order.order_id">
                <td>{{ order.order_id }}</td>
                <td>{{ formatExchange(order.exchange) }}</td>
                <td>{{ order.symbol }}</td>
                <td>{{ formatAction(order.side) }}</td>
                <td>{{ formatMoney(order.price, 0) }}</td>
                <td>{{ order.quantity }}</td>
                <td><StatusBadge :label="formatStatus(order.status)" :tone="orderStatusTone(order.status)" /></td>
                <td>
                  <button type="button" class="compact-button" :disabled="orderSubmitting" @click="cancelOrder(order)">撤单</button>
                </td>
              </tr>
            </tbody>
          </table>
        </SectionPanel>

        <SectionPanel title="操作区" note="真实动作必须二次确认">
          <div class="panel-body grid">
            <div class="toolbar-row">
              <span class="inline-status">当前模式：{{ selectedModeLabel }}</span>
            </div>
            <div class="form-grid">
              <div class="form-field">
                <label>交易所</label>
                <select v-model="liveExchange">
                  <option value="binance">币安</option>
                  <option value="okx">OKX</option>
                </select>
              </div>
              <div class="form-field">
                <label>币种</label>
                <input v-model="orderDraft.symbol" />
              </div>
              <div class="form-field">
                <label>动作</label>
                <select v-model="orderDraft.action">
                  <option
                    v-for="option in tradeMode === 'live' ? liveActionOptions : actionOptions"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
              </div>
              <div class="form-field">
                <label>类型</label>
                <select v-model="orderDraft.order_type">
                  <option value="market">市价</option>
                  <option value="limit">限价</option>
                </select>
              </div>
              <div class="form-field">
                <label>数量</label>
                <input v-model.number="orderDraft.quantity" type="number" min="0" step="0.0001" />
              </div>
              <div class="form-field">
                <label>价格</label>
                <input v-model.number="orderDraft.price" type="number" min="0" step="0.01" />
              </div>
            </div>
            <div class="toolbar-row">
              <button v-if="tradeMode === 'dry_run'" type="button" class="primary-button" :disabled="orderSubmitting" @click="submitDryRunOrder">
                {{ orderSubmitting ? '校验中' : '模拟校验' }}
              </button>
              <button v-else type="button" class="danger-button" :disabled="orderSubmitting || !canSubmitLiveOrder" @click="submitLiveOrder">
                {{ orderSubmitting ? '提交中' : '实盘下单' }}
              </button>
              <button type="button" class="icon-text-button" :disabled="controlSubmitting" @click="toggleStrategyPause">
                {{ systemStore.paused ? '恢复策略' : '暂停策略' }}
              </button>
              <button type="button" class="danger-button" :disabled="controlSubmitting" @click="triggerKillSwitch">紧急停止</button>
            </div>
            <div v-if="controlError" class="result-message negative">{{ controlError }}</div>
            <div v-else-if="controlMessage" class="result-message">{{ controlMessage }}</div>
            <div v-if="orderError" class="result-message negative">{{ orderError }}</div>
            <div v-else-if="orderResult" class="result-message">
              <strong>{{ formatStatus(orderResult.status) }}</strong>
              <span>{{ orderResult.order_id }} · {{ orderResult.symbol }} · {{ formatAction(orderResult.side) }}</span>
            </div>
          </div>
        </SectionPanel>
      </div>

      <SectionPanel title="历史订单" note="用于对账和复盘">
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>订单编号</th>
              <th>交易所</th>
              <th>币种</th>
              <th>方向</th>
              <th>类型</th>
              <th>价格</th>
              <th>数量</th>
              <th>手续费</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in data.historical_orders" :key="order.order_id">
              <td>{{ formatDateTime(order.created_at) }}</td>
              <td>{{ order.order_id }}</td>
              <td>{{ formatExchange(order.exchange) }}</td>
              <td>{{ order.symbol }}</td>
              <td>{{ formatAction(order.side) }}</td>
              <td>{{ formatAction(order.order_type) }}</td>
              <td>{{ formatMoney(order.price, 0) }}</td>
              <td>{{ order.quantity }}</td>
              <td>{{ order.fee ? formatMoney(order.fee) : '-' }}</td>
              <td><StatusBadge :label="formatStatus(order.status)" :tone="orderStatusTone(order.status)" /></td>
            </tr>
          </tbody>
        </table>
      </SectionPanel>
    </template>
  </div>
</template>
