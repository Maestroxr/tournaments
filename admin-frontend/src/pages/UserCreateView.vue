<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import AppAlert from '@/components/AppAlert.vue'
import WalletAdjustmentPanel from '@/components/WalletAdjustmentPanel.vue'
import UserAccessSettingsCard from '@/components/user/UserAccessSettingsCard.vue'
import UserAccountDetailsCard from '@/components/user/UserAccountDetailsCard.vue'
import UserPasswordCard from '@/components/user/UserPasswordCard.vue'
import UserSummaryCard from '@/components/user/UserSummaryCard.vue'
import { apiFetch, apiFieldErrors, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

type CreatedUser = {
  id: number
  username: string
  phone_number: string
  is_staff: boolean
  balance: string
}

const router = useRouter()
const username = ref('')
const phoneNumber = ref('')
const password = ref('')
const isStaff = ref(false)
const initialBalance = ref<number | null>(null)
const error = ref('')
const submitted = ref(false)
const loading = ref(false)
const copied = ref(false)
const createdUser = ref<CreatedUser | null>(null)
const createdPassword = ref('')
const serverFieldErrors = ref<Record<string, string>>({})
const { direction, t } = useI18n()

const clientFieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = t('users.usernameRequired')
  else if (!/^[A-Za-z0-9]+$/.test(username.value.trim())) errs.username = t('users.usernameCharacters')
  if (!password.value) errs.password1 = t('users.passwordRequired')
  if (phoneNumber.value && !/^\+?[0-9 ()-]+$/.test(phoneNumber.value)) errs.phone_number = t('users.validPhone')
  else if (phoneNumber.value) {
    const digitCount = phoneNumber.value.replace(/\D/g, '').length
    if (digitCount < 7 || digitCount > 15) errs.phone_number = t('users.validPhone')
  }
  if (initialBalance.value !== null && (!Number.isFinite(initialBalance.value) || initialBalance.value < 0)) {
    errs.initial_balance = t('users.initialBalanceInvalid')
  }
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

function normalizeCreateErrors(errors: Record<string, string>) {
  const normalized = { ...errors }
  if (normalized.password2) {
    normalized.password1 = [normalized.password1, normalized.password2].filter(Boolean).join(' ')
    delete normalized.password2
  }
  return normalized
}

async function copyCredentials() {
  if (!createdUser.value || !navigator.clipboard) return
  await navigator.clipboard.writeText(`${t('users.username')}: ${createdUser.value.username}\n${t('users.password')}: ${createdPassword.value}`)
  copied.value = true
}

function createAnother() {
  username.value = ''
  phoneNumber.value = ''
  password.value = ''
  isStaff.value = false
  initialBalance.value = null
  error.value = ''
  submitted.value = false
  copied.value = false
  createdUser.value = null
  createdPassword.value = ''
  serverFieldErrors.value = {}
}

async function create() {
  submitted.value = true
  error.value = ''
  serverFieldErrors.value = {}
  if (hasErrors.value) { error.value = t('users.reviewFields'); return }
  loading.value = true
  try {
    const savedPassword = password.value
    createdUser.value = await apiFetch<CreatedUser>('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: username.value.trim(), phone_number: phoneNumber.value.trim(),
        password1: savedPassword, password2: savedPassword, is_staff: isStaff.value,
        initial_balance: initialBalance.value ?? 0,
      }),
    })
    createdPassword.value = savedPassword
  } catch (caught: unknown) {
    serverFieldErrors.value = normalizeCreateErrors(apiFieldErrors(caught))
    if (Object.keys(serverFieldErrors.value).length) {
      const details = [...new Set(Object.values(serverFieldErrors.value))].join(' ')
      error.value = `${t('users.reviewFields')} ${details}`
    } else {
      error.value = formatApiError(caught)
    }
  } finally { loading.value = false }
}
</script>

<template>
  <div class="mx-auto w-full max-w-4xl">
    <header class="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-sky-400/25 bg-sky-400/10 px-3 py-1 text-xs font-semibold text-sky-200"><i class="bi bi-person-plus-fill" /> {{ t('users.quickBadge') }}</div>
        <h1 class="text-3xl font-bold text-black">{{ t('users.createTitle') }}</h1>
        <p class="mt-1 text-sm text-zinc-600">{{ t('users.intro') }}</p>
      </div>
      <Button type="button" :label="t('common.cancel')" severity="secondary" text @click="router.push('/users')" />
    </header>

    <section v-if="createdUser" class="overflow-hidden rounded-xl border border-emerald-400/30 bg-white shadow-sm">
      <div class="bg-emerald-400/10 p-6 text-center sm:p-8">
        <span class="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-400/20 text-2xl text-emerald-200"><i class="bi bi-check-lg" /></span>
        <h2 class="mt-4 text-2xl font-bold text-black">{{ t('users.createdTitle') }}</h2>
        <p class="mt-1 text-sm text-zinc-600">{{ t('users.createdSubtitle', { name: createdUser.username }) }}</p>
      </div>
      <div class="mx-auto max-w-xl space-y-4 p-6 sm:p-8">
        <div class="rounded-xl border border-zinc-200 bg-zinc-50 p-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div><p class="text-xs text-zinc-500">{{ t('users.username') }}</p><p class="mt-1 font-semibold text-black">{{ createdUser.username }}</p></div>
            <div><p class="text-xs text-zinc-500">{{ t('users.temporaryPassword') }}</p><p class="mt-1 break-all font-mono font-semibold text-black">{{ createdPassword }}</p></div>
          </div>
          <p class="mt-4 flex items-start gap-2 text-xs text-amber-200"><i class="bi bi-exclamation-triangle mt-0.5" /> {{ t('users.passwordShownOnce') }}</p>
        </div>
        <Button type="button" class="w-full" :label="copied ? t('users.copied') : t('users.copyCredentials')" :icon="copied ? 'bi bi-check2' : 'bi bi-copy'" severity="info" outlined @click="copyCredentials" />
        <WalletAdjustmentPanel :user="createdUser" deposit-only />
        <div class="grid gap-2 sm:grid-cols-2">
          <Button type="button" :label="t('users.createAnother')" icon="bi bi-person-plus" severity="success" @click="createAnother" />
          <Button type="button" :label="t('users.backToUsers')" icon="bi bi-people" severity="secondary" outlined @click="router.push('/users')" />
        </div>
      </div>
    </section>

    <form v-else class="grid items-start gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,.75fr)]" @submit.prevent="create">
      <div class="space-y-5">
        <AppAlert v-if="error" type="error" :message="error" dismissible @close="error = ''" />
        <UserAccountDetailsCard v-model:username="username" v-model:phone-number="phoneNumber" :errors="fieldErrors" @changed="clearServerError" />
        <UserPasswordCard v-model="password" :error="fieldErrors.password1" @changed="clearServerError('password1')" />
        <UserAccessSettingsCard v-model:is-staff="isStaff" v-model:opening-balance="initialBalance" show-opening-balance :balance-error="fieldErrors.initial_balance" />
      </div>

      <aside class="lg:sticky lg:top-5">
        <UserSummaryCard :username="username" :phone-number="phoneNumber" :is-staff="isStaff" :balance="initialBalance" balance-type="opening">
          <ul class="space-y-2 text-xs text-zinc-500"><li class="flex items-center gap-2"><i class="bi bi-check-circle text-emerald-300" /> {{ t('users.singlePassword') }}</li><li class="flex items-center gap-2"><i class="bi bi-check-circle text-emerald-300" /> {{ t('users.credentialsAfterCreate') }}</li></ul>
          <template #actions><Button type="submit" class="w-full" :label="loading ? t('common.creating') : t('users.createTitle')" :loading="loading" severity="success" icon="bi bi-person-check" :icon-pos="direction === 'rtl' ? 'right' : 'left'" /></template>
        </UserSummaryCard>
      </aside>
    </form>
  </div>
</template>
