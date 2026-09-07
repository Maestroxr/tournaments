<script setup lang="ts">
import { computed, ref } from 'vue'
import AutoComplete, { type AutoCompleteCompleteEvent } from 'primevue/autocomplete'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'
import { apiFetch, formatApiError } from '@/services/api'

interface WalletUser {
  id: number
  username: string
  phone_number: string
  balance: string
}

type WalletResponse = WalletUser

const props = withDefaults(defineProps<{
  user?: WalletUser | null
  depositOnly?: boolean
}>(), {
  user: null,
  depositOnly: false,
})

const emit = defineEmits<{
  adjusted: [payload: { userId: number; action: 'deposit' | 'withdraw' }]
}>()

const { t } = useI18n()
const selectedUser = ref<WalletUser | string | null>(props.user)
const suggestions = ref<WalletUser[]>([])
const amount = ref<number | null>(null)
const note = ref('')
const searching = ref(false)
const submitting = ref(false)
const error = ref('')
const success = ref('')
let searchSequence = 0

const hasValidAmount = computed(() => {
  const value = Number(amount.value)
  return Number.isFinite(value) && value > 0
})
const chosenUser = computed(() => {
  const value = selectedUser.value
  return value && typeof value === 'object' ? value : null
})

async function searchUsers(event: AutoCompleteCompleteEvent) {
  const sequence = ++searchSequence
  searching.value = true
  error.value = ''
  try {
    const query = event.query.trim()
    const suffix = query ? `?q=${encodeURIComponent(query)}` : ''
    const users = await apiFetch<WalletUser[]>(`/api/admin/users${suffix}`)
    if (sequence === searchSequence) suggestions.value = users
  } catch (caught: unknown) {
    if (sequence === searchSequence) error.value = formatApiError(caught)
  } finally {
    if (sequence === searchSequence) searching.value = false
  }
}

async function adjust(action: 'deposit' | 'withdraw') {
  error.value = ''
  success.value = ''
  const walletUser = chosenUser.value
  if (!walletUser) {
    error.value = t('transfers.selectUserRequired')
    return
  }
  if (!hasValidAmount.value) {
    error.value = t('users.positiveAmount')
    return
  }

  submitting.value = true
  try {
    const user = await apiFetch<WalletResponse>(`/api/admin/users/${walletUser.id}/wallet`, {
      method: 'POST',
      body: JSON.stringify({ action, amount: amount.value, note: note.value.trim() }),
    })
    selectedUser.value = { ...walletUser, balance: user.balance }
    amount.value = null
    note.value = ''
    success.value =
      action === 'deposit'
        ? t('transfers.depositSuccess', { user: user.username })
        : t('transfers.withdrawSuccess', { user: user.username })
    emit('adjusted', { userId: user.id, action })
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="wallet-adjustment-panel mb-6 overflow-hidden rounded-lg border shadow-sm">
    <div class="wallet-adjustment-header border-b px-5 py-4">
      <h2 class="wallet-adjustment-title text-lg font-bold">
        {{ depositOnly && chosenUser ? t('transfers.walletDepositTitle', { user: chosenUser.username }) : t('transfers.walletTitle') }}
      </h2>
      <p class="wallet-adjustment-subtitle mt-1 text-sm">
        {{ depositOnly && chosenUser ? t('transfers.walletDepositSubtitle') : t('transfers.walletSubtitle') }}
      </p>
    </div>

    <div class="space-y-4 p-5">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error = ''" />
      <AppAlert
        v-if="success"
        type="success"
        :message="success"
        dismissible
        @close="success = ''"
      />

      <div
        :class="[
          'grid gap-4',
          user
            ? 'sm:grid-cols-[minmax(130px,0.5fr)_minmax(220px,1fr)]'
            : 'lg:grid-cols-[minmax(240px,1.4fr)_minmax(130px,0.5fr)_minmax(220px,1fr)]',
        ]"
      >
        <label v-if="!user" class="block min-w-0">
          <span class="mb-1.5 block text-sm font-semibold text-zinc-800">{{
            t('transfers.selectUser')
          }}</span>
          <AutoComplete
            v-model="selectedUser"
            :suggestions="suggestions"
            option-label="username"
            :placeholder="t('transfers.searchUser')"
            :loading="searching"
            force-selection
            dropdown
            fluid
            @complete="searchUsers"
          >
            <template #option="{ option }">
              <div class="flex w-full items-center justify-between gap-4 py-1">
                <div class="min-w-0">
                  <div class="truncate font-semibold text-white">{{ option.username }}</div>
                  <div class="truncate text-xs text-zinc-500">
                    {{ option.phone_number || t('common.noPhone') }}
                  </div>
                </div>
                <span class="shrink-0 text-sm font-semibold text-emerald-700">{{
                  Number(option.balance || 0).toFixed(2)
                }}</span>
              </div>
            </template>
          </AutoComplete>
        </label>

        <label class="block">
          <span class="mb-1.5 block text-sm font-semibold text-zinc-800">{{
            t('common.amount')
          }}</span>
          <InputNumber
            v-model="amount"
            :min="0.01"
            :min-fraction-digits="2"
            :max-fraction-digits="2"
            :placeholder="t('common.amount')"
            fluid
          />
        </label>

        <label class="block min-w-0">
          <span class="mb-1.5 block text-sm font-semibold text-zinc-800">{{
            t('common.note')
          }}</span>
          <InputText
            v-model="note"
            :placeholder="t('transfers.notePlaceholder')"
            class="w-full"
            maxlength="255"
          />
        </label>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
        <p class="text-sm text-zinc-600">
          <template v-if="chosenUser">
            {{ chosenUser.username }} · {{ t('users.currentBalance') }}:
            <span class="font-bold text-emerald-700">{{
              Number(chosenUser.balance || 0).toFixed(2)
            }}</span>
          </template>
          <template v-else>{{ t('transfers.selectUserHint') }}</template>
        </p>
        <div class="flex gap-2">
          <Button
            type="button"
            :label="t('users.deposit')"
            icon="bi bi-plus-lg"
            severity="success"
            :disabled="!chosenUser || !hasValidAmount"
            :loading="submitting"
            @click="adjust('deposit')"
          />
          <Button
            v-if="!depositOnly"
            type="button"
            :label="t('users.withdraw')"
            icon="bi bi-dash-lg"
            severity="danger"
            outlined
            :disabled="!chosenUser || !hasValidAmount"
            :loading="submitting"
            @click="adjust('withdraw')"
          />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wallet-adjustment-panel {
  border-color: #263653;
  background: #111a30;
}

.wallet-adjustment-header {
  border-color: #31425f;
  background: #151f38;
}

.wallet-adjustment-title {
  color: #f3f6ff;
}

.wallet-adjustment-subtitle {
  color: #aab8d4;
}
</style>
