<script setup lang="ts">
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { useI18n } from '@/i18n'

interface WalletTransaction {
  id: number
  kind: string
  amount: string
  balance_after: string
  tournament_name: string | null
  note: string
  created_at: string
}

defineProps<{ transactions: WalletTransaction[] }>()
const { t } = useI18n()

function formatDate(value: string) {
  try { return new Date(value).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) } catch { return value }
}
</script>

<template>
  <section class="overflow-hidden rounded-xl border border-zinc-200 bg-white">
    <div class="border-b border-zinc-200 bg-zinc-50 px-5 py-4 sm:px-6">
      <h2 class="text-lg font-semibold text-black">{{ t('users.recentWalletActivity') }}</h2>
    </div>
    <div class="overflow-x-auto p-5 sm:p-6">
      <DataTable :value="transactions" data-key="id" size="small" striped-rows show-gridlines>
        <template #empty>{{ t('users.noWallet') }}</template>
        <Column :header="t('transfers.date')" sortable sort-field="created_at"><template #body="{ data }">{{ formatDate(data.created_at) }}</template></Column>
        <Column field="kind" :header="t('common.type')" sortable />
        <Column :header="t('common.amount')" sortable sort-field="amount" body-class="text-right"><template #body="{ data }"><span :class="['font-medium', Number(data.amount) >= 0 ? 'text-emerald-700' : 'text-red-700']">{{ Number(data.amount).toFixed(2) }}</span></template></Column>
        <Column :header="t('users.balance')" sortable sort-field="balance_after" body-class="text-right"><template #body="{ data }">{{ Number(data.balance_after).toFixed(2) }}</template></Column>
        <Column :header="t('common.note')"><template #body="{ data }">{{ data.tournament_name || data.note || '-' }}</template></Column>
      </DataTable>
    </div>
  </section>
</template>
