<script setup lang="ts">
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'

defineProps<{ modelValue: string; label?: string; placeholder?: string; type?: string; error?: string; autocomplete?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'keydown', ev: KeyboardEvent): void }>()

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') emit('keydown', event)
}
</script>
<template>
  <label class="block">
    <span v-if="label" class="mb-1 block text-sm font-medium">{{ label }}</span>
    <Password
      v-if="type === 'password'"
      :model-value="modelValue"
      :placeholder="placeholder"
      :input-props="{ autocomplete, onKeydown: handleKeydown }"
      :feedback="false"
      toggle-mask
      fluid
      :invalid="Boolean(error)"
      @update:model-value="emit('update:modelValue', String($event ?? ''))"
    />
    <InputText
      v-else
      :type="type ?? 'text'"
      :model-value="modelValue"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      class="w-full"
      :invalid="Boolean(error)"
      @update:model-value="emit('update:modelValue', String($event ?? ''))"
      @keydown="handleKeydown"
    />
    <p v-if="error" class="mt-1 text-xs text-red-500">{{ error }}</p>
  </label>
</template>
