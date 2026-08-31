<script setup lang="ts">
defineProps<{ modelValue: string; placeholder?: string }>()
defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'search', v: string): void }>()
</script>
<template>
  <div class="flex gap-2">
    <input
      :value="modelValue"
      :placeholder="placeholder ?? 'Search...'"
      class="w-full rounded border px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500 focus:outline-none"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keydown.enter="$emit('search', modelValue)"
    />
    <button class="rounded bg-zinc-900 px-4 py-2 text-sm text-white hover:bg-black" @click="$emit('search', modelValue)">Search</button>
  </div>
</template>
