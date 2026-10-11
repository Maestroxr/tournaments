<script setup lang="ts">
import { useId } from 'vue'
const value = defineModel<number>({ required: true })
defineProps<{
  label: string
  min?: number
  max?: number
  step?: number
  hint?: string
  error?: string
  required?: boolean
}>()
const id = useId()
</script>
<template>
  <div class="space-y-2">
    <label :for="id" class="block text-sm font-semibold text-neutral-200">{{ label }}</label>
    <input
      :id="id"
      v-model.number="value"
      type="number"
      :min="min"
      :max="max"
      :step="step ?? 1"
      :required="required ?? true"
      dir="ltr"
      :aria-invalid="Boolean(error)"
      :aria-describedby="hint || error ? id + '-help' : undefined"
      class="min-h-11 w-full rounded-lg border border-white/20 bg-neutral-900 px-3 py-2 text-start text-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c] disabled:opacity-60"
    />
    <div v-if="hint || error" :id="id + '-help'" class="space-y-1 text-xs leading-relaxed">
      <p v-if="hint" class="text-neutral-400">{{ hint }}</p>
      <p v-if="error" class="text-red-300">{{ error }}</p>
    </div>
  </div>
</template>
