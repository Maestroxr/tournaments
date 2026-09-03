<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import ToggleSwitch from 'primevue/toggleswitch'
import AppInput from '@/components/AppInput.vue'
import AppAlert from '@/components/AppAlert.vue'
import { apiFetch, apiFieldErrors, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

const router = useRouter()
const username = ref('')
const email = ref('')
const password1 = ref('')
const password2 = ref('')
const is_staff = ref(false)
const error = ref('')
const submitted = ref(false)
const loading = ref(false)
const serverFieldErrors = ref<Record<string, string>>({})
const { t } = useI18n()

const clientFieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = t('users.usernameRequired')
  else if (/^testuser-[0-9]+$/.test(username.value.trim())) errs.username = t('users.usernameReserved')
  if (!password1.value) errs.password1 = t('users.passwordRequired')
  if (password1.value !== password2.value) errs.password2 = t('users.passwordsMustMatch')
  if (email.value && !/^\S+@\S+\.\S+$/.test(email.value)) errs.email = t('users.validEmail')
  return errs
})
const visibleClientErrors = computed(() => submitted.value ? clientFieldErrors.value : {})
const fieldErrors = computed(() => ({ ...serverFieldErrors.value, ...visibleClientErrors.value }))
const hasErrors = computed(() => Object.keys(clientFieldErrors.value).length > 0)

function clearServerError(field: string) {
  if (!serverFieldErrors.value[field]) return
  const next = { ...serverFieldErrors.value }
  delete next[field]
  serverFieldErrors.value = next
}

async function create() {
  submitted.value = true
  error.value = ''
  serverFieldErrors.value = {}
  if (hasErrors.value) { error.value = t('users.reviewFields'); return }
  loading.value = true
  try {
    await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: username.value.trim(),
        email: email.value.trim(),
        password1: password1.value,
        password2: password2.value,
        is_staff: is_staff.value,
      }),
    })
    router.push('/users')
  } catch (caught: unknown) {
    serverFieldErrors.value = apiFieldErrors(caught)
    error.value = Object.keys(serverFieldErrors.value).length
      ? t('users.reviewFields')
      : formatApiError(caught)
  } finally { loading.value = false }
}
</script>

<template>
  <div class="mx-auto w-full max-w-lg">
    <h1 class="mb-1 text-2xl font-bold text-black">{{ t('users.createTitle') }}</h1>
    <p class="mb-4 text-sm text-zinc-600">{{ t('users.intro') }}</p>
    <AppAlert v-if="error" class="mb-5" type="error" :message="error" dismissible @close="error = ''" />
    <form @submit.prevent="create" class="space-y-4">
      <div class="grid gap-4 sm:grid-cols-2">
        <AppInput v-model="username" :label="t('users.username')" :placeholder="t('users.username')" :error="fieldErrors.username" autocomplete="username" @update:model-value="clearServerError('username')" />
        <AppInput v-model="email" :label="t('users.emailOptional')" placeholder="email@example.com" type="email" :error="fieldErrors.email" autocomplete="email" @update:model-value="clearServerError('email')" />
        <AppInput v-model="password1" :label="t('users.password')" type="password" :placeholder="t('users.password')" :error="fieldErrors.password1" autocomplete="new-password" @update:model-value="clearServerError('password1')" />
        <AppInput v-model="password2" :label="t('users.confirmPassword')" type="password" :placeholder="t('users.confirmPassword')" :error="fieldErrors.password2" autocomplete="new-password" @update:model-value="clearServerError('password2')" />
      </div>
      <label class="flex items-center gap-3 text-sm text-black"><ToggleSwitch v-model="is_staff" /> {{ t('users.staffAccess') }}</label>

      <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-600">
        {{ t('users.preview') }}: <span class="font-medium text-black">{{ username || '—' }}</span> • {{ email || t('common.noEmail') }} • {{ is_staff ? t('common.staff') : t('common.user') }}
      </div>

      <div class="flex gap-2">
        <Button type="submit" :label="loading ? t('common.creating') : t('users.createTitle')" :loading="loading" severity="info" />
        <Button :label="t('common.cancel')" severity="secondary" outlined @click="router.push('/users')" />
      </div>
    </form>
  </div>
</template>
