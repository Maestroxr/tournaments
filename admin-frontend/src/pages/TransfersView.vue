<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import AutoComplete, { type AutoCompleteCompleteEvent } from 'primevue/autocomplete'
import WalletAdjustmentPanel from '@/components/WalletAdjustmentPanel.vue'
import { transferKindLabel } from '@/utils/adminLabels'
import { useI18n } from '@/i18n'

interface Transfer {
  id: number
  username: string
  kind: string
  amount: string
  balance_after: string
  tournament_name: string | null
  actor_username: string | null
  note: string
  created_at: string
}

const transfers = ref<Transfer[]>([])
const loading = ref(false)
const error = ref('')
const { locale, t } = useI18n()
interface UserOption { id: number; username: string; phone_number: string }
const selectedUser = ref<UserOption | string | null>(null)
const userOptions = ref<UserOption[]>([])
const userSearchError = ref('')
const offset = ref(0)
const pageSize = 50
const count = ref(0)
let loadSequence = 0
let searchSequence = 0

async function searchUsers(event: AutoCompleteCompleteEvent) {
  const sequence = ++searchSequence
  userSearchError.value = ''
  try {
    const users = await apiFetch<UserOption[]>(`/api/admin/users?q=${encodeURIComponent(event.query.trim())}`)
    if (sequence === searchSequence) userOptions.value = users
  } catch (caught) {
    if (sequence === searchSequence) userSearchError.value = formatApiError(caught)
  }
}

watch(() => typeof selectedUser.value === 'object' ? selectedUser.value?.id : null, () => {
  offset.value = 0
  void load()
})

function changePage(delta: number) {
  offset.value = Math.max(0, offset.value + delta * pageSize)
  void load()
}

async function load() {
  const sequence = ++loadSequence
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset.value) })
    if (selectedUser.value && typeof selectedUser.value === 'object') query.set('user_id', String(selectedUser.value.id))
    const data = await apiFetch<{ items: Transfer[]; count: number }>(`/api/admin/wallet-transactions?${query}`)
    if (sequence === loadSequence) {
      transfers.value = data.items
      count.value = data.count
    }
  } catch (caught: unknown) {
    if (sequence === loadSequence) error.value = formatApiError(caught)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function formatDate(value: string) {
  try { return new Date(value).toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-GB', { dateStyle: 'short', timeStyle: 'short' }) } catch { return value }
}

onMounted(load)
</script>

<template>
  <section aria-labelledby="transactions-heading">
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 id="transactions-heading" class="text-xl font-semibold text-black">{{ t('transfers.title') }}</h2>
        <p class="mt-1 text-sm text-zinc-500">{{ t('transfers.subtitle') }}</p>
      </div>
      <Button :label="t('common.refresh')" size="small" severity="secondary" outlined @click="load" />
    </div>

    <WalletAdjustmentPanel @adjusted="load" />

    <div class="mb-4 flex flex-wrap items-end gap-3">
      <label class="block w-full max-w-sm">
        <span class="mb-1 block text-sm">{{ t('transfers.filterUser') }}</span>
        <AutoComplete v-model="selectedUser" :suggestions="userOptions" option-label="username" :placeholder="t('transfers.searchUser')" force-selection dropdown fluid @complete="searchUsers">
          <template #option="{ option }">
            <span class="text-inherit">{{ option.username }} <small>{{ option.phone_number }}</small></span>
          </template>
        </AutoComplete>
      </label>
      <Button :label="t('transfers.allUsers')" severity="secondary" outlined @click="selectedUser = null" />
      <span class="text-sm">{{ t('transfers.resultCount', { count }) }}</span>
    </div>
    <p v-if="userSearchError" role="alert" class="mb-3 text-red-400">{{ userSearchError }}</p>

    <div v-if="error" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ error }}</div>
    <DataTable v-else :value="transfers" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>{{ t('transfers.empty') }}</template>
      <Column :header="t('transfers.date')" sortable sort-field="created_at">
        <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
      </Column>
      <Column field="username" :header="t('common.user')" sortable />
      <Column :header="t('common.type')" sortable sort-field="kind">
        <template #body="{ data }">{{ transferKindLabel(data.kind, t) }}</template>
      </Column>
      <Column :header="t('transfers.tournament')">
        <template #body="{ data }">{{ data.tournament_name || '-' }}</template>
      </Column>
      <Column :header="t('common.amount') + (locale === 'he' ? ' (קויינס)' : ' (coins)')" sortable sort-field="amount" body-class="text-right">
        <template #body="{ data }"><span :class="['font-semibold', Number(data.amount) >= 0 ? 'text-emerald-700' : 'text-red-700']">{{ Number(data.amount).toFixed(2) }}</span></template>
      </Column>
      <Column :header="t('users.balance') + (locale === 'he' ? ' (קויינס)' : ' (coins)')" sortable sort-field="balance_after" body-class="text-right">
        <template #body="{ data }">{{ Number(data.balance_after).toFixed(2) }}</template>
      </Column>
      <Column :header="t('common.actor')">
        <template #body="{ data }">{{ data.actor_username || '-' }}</template>
      </Column>
      <Column :header="t('common.note')">
        <template #body="{ data }">{{ data.note || '-' }}</template>
      </Column>
    </DataTable>
    <nav v-if="count > pageSize" class="mt-4 flex justify-end gap-2" :aria-label="t('transfers.title')">
      <Button :label="t('transfers.previousPage')" severity="secondary" :disabled="loading || offset === 0" @click="changePage(-1)" />
      <Button :label="t('transfers.nextPage')" severity="secondary" :disabled="loading || offset + pageSize >= count" @click="changePage(1)" />
    </nav>
  </section>
</template>
