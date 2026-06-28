<script setup lang="ts">
import { computed, watch } from 'vue'

import {
  useMarketSymbols,
  type ExchangeId,
} from '../config/markets'

const props = defineProps<{
  modelValue: string
  exchange: ExchangeId
  label?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const {
  symbolOptions,
  isMarketSymbolSupported,
  firstMarketSymbolForExchange,
} = useMarketSymbols(computed(() => props.exchange))

const selectedSymbol = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

watch(() => props.exchange, (exchange) => {
  if (!isMarketSymbolSupported(props.modelValue, exchange)) {
    emit('update:modelValue', firstMarketSymbolForExchange(exchange))
  }
})
</script>

<template>
  <div class="market-symbol-select">
    <label v-if="label">{{ label }}</label>
    <select v-model="selectedSymbol" :disabled="disabled">
      <option v-for="option in symbolOptions" :key="option.symbol" :value="option.symbol">
        {{ option.symbol }}{{ option.builtIn ? '' : ' · 自定义' }}
      </option>
    </select>
  </div>
</template>
