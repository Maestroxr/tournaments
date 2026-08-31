<script setup lang="ts">
defineProps<{ modelValue: string; label?: string; placeholder?: string; type?: string; error?: string; autocomplete?: string }>()
defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'keydown', ev: KeyboardEvent): void }>()
</script>
<template>
  <label class="block">
    <span v-if="label" class="mb-1 block text-sm font-medium">{{ label }}</span>
    <input
      :type="type ?? 'text'"
      :value="modelValue"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      class="w-full rounded border px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500 focus:outline-none"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keydown.enter="$emit('keydown', $event)"
    />
    <p v-if="error" class="mt-1 text-xs text-red-500">{{ error }}</p>
  </label>
</template>
