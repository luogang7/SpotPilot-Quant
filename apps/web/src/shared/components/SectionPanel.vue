<script setup lang="ts">
defineProps<{
  title: string
  note?: string
}>()
</script>

<template>
  <section class="section-panel">
    <header class="section-panel__head">
      <h2>{{ title }}</h2>
      <span v-if="note">{{ note }}</span>
      <slot name="actions"></slot>
    </header>
    <slot></slot>
  </section>
</template>

