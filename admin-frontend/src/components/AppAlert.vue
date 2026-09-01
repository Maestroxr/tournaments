<script setup lang="ts">
import Message from 'primevue/message'

defineProps<{
  type?: 'error' | 'success' | 'warning' | 'info'
  message: string
  dismissible?: boolean
}>()

defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <Message :severity="type ?? 'error'" :closable="dismissible" @close="$emit('close')">{{ message }}</Message>
</template>
