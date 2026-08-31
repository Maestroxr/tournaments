<script setup lang="ts">
defineProps<{
  type?: 'error' | 'success' | 'warning' | 'info'
  message: string
  dismissible?: boolean
}>()

defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <div
    role="alert"
    class="flex items-start gap-2 rounded border px-4 py-3 text-sm"
    :class="{
      'border-red-200 bg-red-50 text-red-800': (type ?? 'error') === 'error',
      'border-green-200 bg-green-50 text-green-800': type === 'success',
      'border-amber-200 bg-amber-50 text-amber-800': type === 'warning',
      'border-sky-200 bg-sky-50 text-sky-800': type === 'info',
    }"
  >
    <i
      class="bi mt-0.5 shrink-0"
      :class="{
        'bi-exclamation-triangle-fill': (type ?? 'error') === 'error',
        'bi-check-circle-fill': type === 'success',
        'bi-exclamation-circle-fill': type === 'warning',
        'bi-info-circle-fill': type === 'info',
      }"
      aria-hidden="true"
    ></i>
    <span class="flex-1">{{ message }}</span>
    <button
      v-if="dismissible"
      type="button"
      class="ml-auto shrink-0 rounded p-1 opacity-60 hover:opacity-100"
      aria-label="Dismiss"
      @click="$emit('close')"
    >
      <i class="bi bi-x-lg text-xs" aria-hidden="true"></i>
    </button>
  </div>
</template>
