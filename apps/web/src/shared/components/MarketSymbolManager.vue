<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'

import { formatExchange } from '../api/format'
import {
  BUILT_IN_MARKET_SYMBOL_OPTIONS,
  marketSymbolValidationMessage,
  normalizeMarketSymbol,
  useMarketSymbols,
  type ExchangeId,
} from '../config/markets'

const {
  customSymbols,
  addCustomSymbol,
  removeCustomSymbol,
} = useMarketSymbols()

const exchangeOptions: ExchangeId[] = ['binance', 'okx']
const draftSymbol = ref('')
const draftExchanges = ref<ExchangeId[]>(['binance', 'okx'])
const feedback = ref('')
const normalizedDraftSymbol = computed(() => normalizeMarketSymbol(draftSymbol.value))
const draftValidationMessage = computed(() => {
  if (!draftSymbol.value.trim()) {
    return ''
  }
  return marketSymbolValidationMessage(draftSymbol.value)
})

function toggleExchange(exchange: ExchangeId) {
  if (draftExchanges.value.includes(exchange)) {
    if (draftExchanges.value.length === 1) {
      return
    }
    draftExchanges.value = draftExchanges.value.filter((item) => item !== exchange)
  } else {
    draftExchanges.value = [...draftExchanges.value, exchange]
  }
}

function addSymbol() {
  feedback.value = ''
  const result = addCustomSymbol({
    symbol: draftSymbol.value,
    exchanges: draftExchanges.value,
  })

  if (!result.ok) {
    feedback.value = result.message
    return
  }

  draftSymbol.value = ''
  draftExchanges.value = ['binance', 'okx']
  feedback.value = `${result.symbol} 已加入自定义币种`
}
</script>

<template>
  <div class="market-symbol-manager">
    <form class="market-symbol-manager__form" @submit.prevent="addSymbol">
      <div class="form-field">
        <label>交易对</label>
        <input
          v-model="draftSymbol"
          placeholder="例如 PEPE/USDT"
          spellcheck="false"
        />
      </div>

      <div class="form-field">
        <label>交易所</label>
        <div class="market-symbol-manager__exchange-group">
          <button
            v-for="exchange in exchangeOptions"
            :key="exchange"
            type="button"
            class="compact-button"
            :class="{ active: draftExchanges.includes(exchange) }"
            @click="toggleExchange(exchange)"
          >
            {{ formatExchange(exchange) }}
          </button>
        </div>
      </div>

      <button
        type="submit"
        class="primary-button"
        :disabled="Boolean(draftValidationMessage) || !draftSymbol.trim() || draftExchanges.length === 0"
      >
        <Plus :size="15" />
        添加币种
      </button>
    </form>

    <div v-if="draftSymbol || feedback" class="market-symbol-manager__hint" :class="{ negative: draftValidationMessage }">
      {{ draftValidationMessage || (normalizedDraftSymbol ? `将添加 ${normalizedDraftSymbol}` : feedback) || feedback }}
    </div>

    <div class="market-symbol-manager__lists">
      <section>
        <header>
          <strong>内置默认币种</strong>
          <span>{{ BUILT_IN_MARKET_SYMBOL_OPTIONS.length }} 个</span>
        </header>
        <div class="market-symbol-manager__chips">
          <span v-for="option in BUILT_IN_MARKET_SYMBOL_OPTIONS" :key="option.symbol" class="market-symbol-chip locked">
            {{ option.symbol }}
            <small>{{ option.exchanges.map(formatExchange).join(' / ') }}</small>
          </span>
        </div>
      </section>

      <section>
        <header>
          <strong>自定义币种</strong>
          <span>{{ customSymbols.length }} 个</span>
        </header>
        <div v-if="customSymbols.length" class="market-symbol-manager__chips">
          <span v-for="option in customSymbols" :key="option.symbol" class="market-symbol-chip">
            {{ option.symbol }}
            <small>{{ option.exchanges.map(formatExchange).join(' / ') }}</small>
            <button type="button" title="删除自定义币种" @click="removeCustomSymbol(option.symbol)">
              <Trash2 :size="13" />
            </button>
          </span>
        </div>
        <div v-else class="market-symbol-manager__empty">暂无自定义币种</div>
      </section>
    </div>
  </div>
</template>
