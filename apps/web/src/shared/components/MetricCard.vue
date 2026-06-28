<script setup lang="ts">
import type { Severity } from '../types/workbench'

defineProps<{
  label: string
  value: string
  detail: string
  severity?: Severity
}>()
</script>

<template>
  <article class="metric-card" :class="severity ?? 'info'">
    <span>{{ label }}</span>
    <strong>{{ value }}</strong>
    <small>{{ detail }}</small>
  </article>
</template>

