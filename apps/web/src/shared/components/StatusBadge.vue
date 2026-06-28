<script setup lang="ts">
import type { ConnectionState, Severity } from '../types/workbench'

defineProps<{
  label: string
  tone?: Severity | ConnectionState
}>()
</script>

<template>
  <span class="status-badge" :class="tone ?? 'info'">
    <span class="status-dot"></span>
    {{ label }}
  </span>
</template>

