<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import AppAlert from '@/components/AppAlert.vue'
import WalletAdjustmentPanel from '@/components/WalletAdjustmentPanel.vue'
import UserAccessSettingsCard from '@/components/user/UserAccessSettingsCard.vue'
import UserAccountDetailsCard from '@/components/user/UserAccountDetailsCard.vue'
import UserPasswordCard from '@/components/user/UserPasswordCard.vue'
import UserSummaryCard from '@/components/user/UserSummaryCard.vue'
import UserWalletActivity from '@/components/user/UserWalletActivity.vue'
import { apiFetch, apiFieldErrors, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string

const username = ref('')
const phoneNumber = ref('')
const is_staff = ref(false)
const is_active = ref(true)
const new_password = ref('')
const balance = ref('0.00')
const transactions = ref<WalletTransaction[]>([])
const error = ref('')
const loading = ref(false)
const fetching = ref(true)
const loadFailed = ref(false)
const submitted = ref(false)
const serverFieldErrors = ref<Record<string, string>>({})
const { direction, t } = useI18n()

interface UserDetail {
  id: number
  username: string
  phone_number?: string
  is_staff?: boolean
  is_active?: boolean
  balance?: string
  transactions?: WalletTransaction[]
}

interface WalletTransaction {
  id: number
  kind: string
  amount: string
  balance_after: string
  tournament_name: string | null
  actor_username: string | null
  note: string
  created_at: string
}

const clientFieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = t('users.usernameRequiredShort')
  else if (!/^[A-Za-z0-9]+$/.test(username.value.trim())) errs.username = t('users.usernameCharactersShort')
  if (phoneNumber.value && !/^\+?[0-9 ()-]+$/.test(phoneNumber.value)) errs.phone_number = t('users.invalidPhone')
  else if (phoneNumber.value) {
    const digitCount = phoneNumber.value.replace(/\D/g, '').length
    if (digitCount < 7 || digitCount > 15) errs.phone_number = t('users.invalidPhone')
  }
  if (new_password.value && new_password.value.length < 8) errs.new_password = t('users.newPasswordTooShort')
  return errs
})
const visibleClientErrors = computed(() => submitted.value ? clientFieldErrors.value : {})
const fieldErrors = computed(() => ({ ...serverFieldErrors.value, ...visibleClientErrors.value }))
const walletUser = computed(() => ({ id: Number(id), username: username.value, phone_number: phoneNumber.value, balance: balance.value }))

function clearServerError(field: string) {
  if (!serverFieldErrors.value[field]) return
  const next = { ...serverFieldErrors.value }
  delete next[field]
  serverFieldErrors.value = next
}

async function loadUser(showLoadFailure = true) {
  try {
    const data = await apiFetch<UserDetail>(`/api/admin/users/${id}`)
    username.value = data.username
    phoneNumber.value = data.phone_number ?? ''
    is_staff.value = !!data.is_staff
    is_active.value = data.is_active ?? true
    balance.value = data.balance ?? '0.00'
    transactions.value = data.transactions ?? []
  } catch (e: unknown) {
    error.value = formatApiError(e)
    if (showLoadFailure) loadFailed.value = true
  } finally {
    if (showLoadFailure) fetching.value = false
  }
}

onMounted(() => loadUser())

async function save() {
  submitted.value = true
  error.value = ''
  serverFieldErrors.value = {}
  if (Object.keys(clientFieldErrors.value).length) { error.value = t('users.reviewEditFields'); return }
  loading.value = true
  try {
    const payload: Record<string, unknown> = { username: username.value.trim(), phone_number: phoneNumber.value.trim(), is_staff: is_staff.value, is_active: is_active.value }
    if (new_password.value) payload.new_password = new_password.value
    await apiFetch(`/api/admin/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    router.push('/users')
  } catch (e: unknown) {
    serverFieldErrors.value = apiFieldErrors(e)
    if (Object.keys(serverFieldErrors.value).length) {
      const details = [...new Set(Object.values(serverFieldErrors.value))].join(' ')
      error.value = `${t('users.reviewEditFields')} ${details}`
    } else {
      error.value = formatApiError(e)
    }
  } finally {
    loading.value = false
  }
}

async function refreshWallet() {
  await loadUser(false)
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <header class="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-sky-400/25 bg-sky-400/10 px-3 py-1 text-xs font-semibold text-sky-200">
          <i class="bi bi-person-gear" /> {{ t('users.editBadge') }}
        </div>
        <h1 class="text-3xl font-bold text-black">{{ t('users.editTitle') }}</h1>
        <p class="mt-1 text-sm text-zinc-600">{{ t('users.editIntro') }}</p>
      </div>
      <Button type="button" :label="t('common.cancel')" severity="secondary" text @click="router.push('/users')" />
    </header>

    <AppAlert v-if="error" class="mb-5" type="error" :message="error" dismissible @close="error = ''" />

    <section v-if="fetching" class="rounded-xl border border-zinc-200 bg-white p-8 text-center">
      <i class="bi bi-arrow-repeat me-2 animate-spin text-sky-300" />
      <span class="text-sm text-zinc-500">{{ t('users.loadingUser') }}</span>
    </section>
    <div v-else-if="loadFailed" class="rounded-xl border border-zinc-200 bg-white p-8 text-center">
      <Button as="router-link" to="/users" :label="t('users.backToUsers')" severity="contrast" />
    </div>

    <template v-else>
      <form class="grid items-start gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(280px,.7fr)]" @submit.prevent="save">
        <div class="space-y-5">
          <UserAccountDetailsCard v-model:username="username" v-model:phone-number="phoneNumber" :errors="fieldErrors" @changed="clearServerError" />
          <UserPasswordCard v-model="new_password" optional :error="fieldErrors.new_password" @changed="clearServerError('new_password')" />
          <UserAccessSettingsCard v-model:is-staff="is_staff" v-model:is-active="is_active" show-active />
        </div>

        <aside class="lg:sticky lg:top-5">
          <UserSummaryCard :username="username" :phone-number="phoneNumber" :is-staff="is_staff" :is-active="is_active" :balance="balance" show-status>
            <template #actions>
              <Button type="submit" class="w-full" :label="loading ? t('common.saving') : t('users.saveChanges')" :loading="loading" severity="success" icon="bi bi-check2-circle" :icon-pos="direction === 'rtl' ? 'right' : 'left'" />
              <Button type="button" class="w-full" :label="t('common.cancel')" severity="secondary" outlined @click="router.push('/users')" />
            </template>
          </UserSummaryCard>
        </aside>
      </form>

      <div class="mt-6"><WalletAdjustmentPanel :user="walletUser" @adjusted="refreshWallet" /></div>
      <UserWalletActivity :transactions="transactions" />
    </template>
  </div>
</template>
