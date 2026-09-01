<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { transferKindLabel } from '@/utils/adminLabels'

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
        <h1 class="text-2xl font-bold text-black">Transfers</h1>
        <p class="mt-1 text-sm text-zinc-500">Wallet deposits, withdrawals, tournament fees, refunds and prizes.</p>
      </div>
      <Button label="Refresh" size="small" severity="secondary" outlined @click="load" />
    </div>

    <div v-if="error" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ error }}</div>
    <DataTable v-else :value="transfers" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>No transfers yet.</template>
      <Column header="Date" sortable sort-field="created_at">
        <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
      </Column>
      <Column field="username" header="User" sortable />
      <Column header="Type" sortable sort-field="kind">
        <template #body="{ data }">{{ transferKindLabel(data.kind) }}</template>
      </Column>
      <Column header="Tournament">
        <template #body="{ data }">{{ data.tournament_name || '-' }}</template>
      </Column>
      <Column header="Amount" sortable sort-field="amount" body-class="text-right">
        <template #body="{ data }"><span :class="['font-semibold', Number(data.amount) >= 0 ? 'text-emerald-700' : 'text-red-700']">{{ Number(data.amount).toFixed(2) }}</span></template>
      </Column>
      <Column header="Balance" sortable sort-field="balance_after" body-class="text-right">
        <template #body="{ data }">{{ Number(data.balance_after).toFixed(2) }}</template>
      </Column>
      <Column header="Actor">
        <template #body="{ data }">{{ data.actor_username || '-' }}</template>
      </Column>
      <Column header="Note">
        <template #body="{ data }">{{ data.note || '-' }}</template>
      </Column>
    </DataTable>
  </div>
</template>
