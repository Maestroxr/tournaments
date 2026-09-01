<script setup lang="ts">
defineProps<{
  label: string
  value: string
}>()
</script>

<template>
  <div>
    <dt class="mb-0.5 text-xs text-zinc-500">{{ label }}</dt>
    <dd class="font-medium text-zinc-800">{{ value }}</dd>
  </div>
</template>
