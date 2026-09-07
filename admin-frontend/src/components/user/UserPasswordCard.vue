<script setup lang="ts">
import { computed } from 'vue'
import Button from 'primevue/button'
import AppInput from '@/components/AppInput.vue'
import { useI18n } from '@/i18n'

const props = withDefaults(defineProps<{
  error?: string
  optional?: boolean
}>(), {
  error: '',
  optional: false,
})

const password = defineModel<string>({ required: true })
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()

const score = computed(() => {
  let value = 0
  if (password.value.length >= 8) value += 1
  if (password.value.length >= 12) value += 1
  if (/[a-z]/.test(password.value) && /[A-Z]/.test(password.value)) value += 1
  if (/\d/.test(password.value) && /[^A-Za-z0-9]/.test(password.value)) value += 1
  return value
})
const label = computed(() => {
  if (!password.value) return props.optional ? t('users.passwordUnchanged') : t('users.passwordNotSet')
  return t(`users.passwordStrength.${Math.max(1, score.value)}`)
})

function generate() {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%'
  const values = new Uint32Array(16)
  crypto.getRandomValues(values)
  password.value = Array.from(values, (value) => alphabet[value % alphabet.length]).join('')
  emit('changed')
}
</script>

<template>
  <section class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-6">
    <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div class="flex items-center gap-3">
        <span class="grid h-9 w-9 place-items-center rounded-lg bg-violet-400/15 text-violet-200">
          <i class="bi bi-key" />
        </span>
        <div>
          <h2 class="text-lg font-semibold text-black">{{ optional ? t('users.security') : t('users.signInPassword') }}</h2>
          <p class="text-xs text-zinc-500">{{ optional ? t('users.newPasswordHint') : t('users.passwordHint') }}</p>
        </div>
      </div>
      <Button
        type="button"
        :label="optional ? t('users.generateNewPassword') : t('users.generatePassword')"
        icon="bi bi-stars"
        size="small"
        severity="secondary"
        outlined
        @click="generate"
      />
    </div>
    <AppInput
      v-model="password"
      :label="optional ? t('users.newPassword') : t('users.password')"
      type="password"
      :placeholder="t('users.passwordPlaceholder')"
      :error="error"
      autocomplete="new-password"
      @update:model-value="emit('changed')"
    />
    <div class="mt-3 flex items-center gap-3">
      <div class="grid flex-1 grid-cols-4 gap-1">
        <span
          v-for="part in 4"
          :key="part"
          :class="['h-1.5 rounded-full', score >= part ? (score >= 3 ? 'bg-emerald-400' : 'bg-amber-400') : 'bg-zinc-100']"
        />
      </div>
      <span class="text-xs text-zinc-500">{{ label }}</span>
    </div>
  </section>
</template>
