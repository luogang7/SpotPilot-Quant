<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  state: 'loading' | 'empty' | 'error' | 'disabled'
  message: string
}>()

const stateLabel = computed(() => {
  const labels = {
    loading: '加载中',
    empty: '暂无数据',
    error: '出错了',
    disabled: '已停用',
  }
  return labels[props.state]
})
</script>

<template>
  <div class="empty-state" :class="state">
    <strong>{{ stateLabel }}</strong>
    <span>{{ message }}</span>
  </div>
</template>
