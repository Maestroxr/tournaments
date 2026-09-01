<script setup lang="ts">
import Button from 'primevue/button'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import InputText from 'primevue/inputtext'

defineProps<{ modelValue: string; placeholder?: string }>()
defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'search', v: string): void }>()
</script>
<template>
  <div class="flex gap-2">
    <IconField class="min-w-0 flex-1">
      <InputIcon class="bi bi-search" />
      <InputText
      :value="modelValue"
      :placeholder="placeholder ?? 'Search...'"
        class="w-full"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keydown.enter="$emit('search', modelValue)"
      />
    </IconField>
    <Button label="Search" size="small" severity="contrast" @click="$emit('search', modelValue)" />
  </div>
</template>
