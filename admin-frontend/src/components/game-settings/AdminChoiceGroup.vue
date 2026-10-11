<script setup lang="ts" generic="T extends string | number | boolean">
import { useId } from 'vue'
const props = defineProps<{
  modelValue: T[]
  options: { value: T; label: string }[]
  label: string
  error?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: T[]] }>()
const id = useId()
function select(value: T) {
  const selected = props.modelValue.includes(value)
  if (selected && props.modelValue.length === 1) return
  emit(
    'update:modelValue',
    selected ? props.modelValue.filter((item) => item !== value) : [...props.modelValue, value],
  )
}
</script>
<template>
  <fieldset class="min-w-0 space-y-3" :aria-describedby="error ? id : undefined">
    <legend class="mb-2 text-sm font-semibold text-neutral-200">{{ label }}</legend>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="option in options"
        :key="String(option.value)"
        type="button"
        :aria-pressed="modelValue.includes(option.value)"
        class="min-h-11 min-w-11 rounded-lg border border-white/20 bg-neutral-900 px-3 py-2 text-sm text-neutral-300 hover:border-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c] disabled:cursor-wait disabled:opacity-60 aria-pressed:border-[#dfbc7c] aria-pressed:bg-[#dfbc7c]/15 aria-pressed:text-[#dfbc7c]"
        @click="select(option.value)"
      >
        {{ option.label }}
      </button>
    </div>
    <p v-if="error" :id="id" class="text-sm text-red-300">{{ error }}</p>
  </fieldset>
</template>
