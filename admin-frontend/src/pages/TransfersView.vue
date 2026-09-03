<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
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
const { t } = useI18n()

async function load() {
  loading.value = true
  error.value = ''
  try {
    transfers.value = await apiFetch<Transfer[]>('/api/admin/transfers')
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

function formatDate(value: string) {
  try { return new Date(value).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) } catch { return value }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-black">{{ t('transfers.title') }}</h1>
        <p class="mt-1 text-sm text-zinc-500">{{ t('transfers.subtitle') }}</p>
      </div>
      <Button :label="t('common.refresh')" size="small" severity="secondary" outlined @click="load" />
    </div>

    <div v-if="error" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ error }}</div>
    <DataTable v-else :value="transfers" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>{{ t('transfers.empty') }}</template>
      <Column :header="t('transfers.date')" sortable sort-field="created_at">
        <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
      </Column>
      <Column field="username" :header="t('common.user')" sortable />
      <Column :header="t('common.type')" sortable sort-field="kind">
        <template #body="{ data }">{{ transferKindLabel(data.kind) }}</template>
      </Column>
      <Column :header="t('transfers.tournament')">
        <template #body="{ data }">{{ data.tournament_name || '-' }}</template>
      </Column>
      <Column :header="t('common.amount')" sortable sort-field="amount" body-class="text-right">
        <template #body="{ data }"><span :class="['font-semibold', Number(data.amount) >= 0 ? 'text-emerald-700' : 'text-red-700']">{{ Number(data.amount).toFixed(2) }}</span></template>
      </Column>
      <Column :header="t('users.balance')" sortable sort-field="balance_after" body-class="text-right">
        <template #body="{ data }">{{ Number(data.balance_after).toFixed(2) }}</template>
      </Column>
      <Column :header="t('common.actor')">
        <template #body="{ data }">{{ data.actor_username || '-' }}</template>
      </Column>
      <Column :header="t('common.note')">
        <template #body="{ data }">{{ data.note || '-' }}</template>
      </Column>
    </DataTable>
  </div>
</template>
