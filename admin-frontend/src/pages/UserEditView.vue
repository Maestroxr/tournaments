<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import ToggleSwitch from 'primevue/toggleswitch'
import AppInput from '@/components/AppInput.vue'
import { apiFetch } from '@/services/api'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string

const username = ref('')
const email = ref('')
const is_staff = ref(false)
const is_active = ref(true)
const new_password = ref('')
const balance = ref('0.00')
const walletAmount = ref<number | null>(null)
const walletNote = ref('')
const transactions = ref<WalletTransaction[]>([])
const error = ref('')
const loading = ref(false)
const fetching = ref(true)

interface UserDetail {
  id: number
  username: string
  email?: string
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

const fieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = 'Username required'
  else if (/^testuser-[0-9]+$/.test(username.value.trim())) errs.username = 'Username reserved'
  if (email.value && !/^\S+@\S+\.\S+$/.test(email.value)) errs.email = 'Invalid email'
  return errs
})

onMounted(async () => {
  try {
    const data = await apiFetch<UserDetail>(`/api/admin/users/${id}`)
    username.value = data.username
    email.value = data.email ?? ''
    is_staff.value = !!data.is_staff
    is_active.value = data.is_active ?? true
    balance.value = data.balance ?? '0.00'
    transactions.value = data.transactions ?? []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load user'
  } finally {
    fetching.value = false
  }
})

async function save() {
  error.value = ''
  if (Object.keys(fieldErrors.value).length) { error.value = Object.values(fieldErrors.value).join(' • '); return }
  loading.value = true
  try {
    const payload: Record<string, unknown> = { username: username.value.trim(), email: email.value.trim(), is_staff: is_staff.value, is_active: is_active.value }
    if (new_password.value) payload.new_password = new_password.value
    await apiFetch(`/api/admin/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    router.push('/users')
  } catch (e: unknown) {
    try { const b = JSON.parse((e as any).body || '{}'); error.value = b.detail || JSON.stringify(b.errors || b) } catch { error.value = e instanceof Error ? e.message : 'Failed' }
  } finally {
    loading.value = false
  }
}

async function wallet(action: 'deposit' | 'withdraw') {
  error.value = ''
  const amount = Number(walletAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) { error.value = 'Enter a positive amount.'; return }
  loading.value = true
  try {
    const data = await apiFetch<UserDetail>(`/api/admin/users/${id}/wallet`, {
      method: 'POST',
      body: JSON.stringify({ action, amount, note: walletNote.value.trim() }),
    })
    balance.value = data.balance ?? '0.00'
    transactions.value = data.transactions ?? []
    walletAmount.value = null
    walletNote.value = ''
  } catch (e: unknown) {
    try { const b = JSON.parse((e as any).body || '{}'); error.value = b.detail || JSON.stringify(b.errors || b) } catch { error.value = e instanceof Error ? e.message : 'Failed' }
  } finally {
    loading.value = false
  }
}

function formatDate(value: string) {
  try { return new Date(value).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) } catch { return value }
}
</script>

<template>
  <div class="mx-auto w-full max-w-lg">
    <h1 class="mb-4 text-2xl font-bold text-black">Edit User</h1>
    <p v-if="fetching" class="text-sm text-zinc-500">Loading…</p>
    <form v-else @submit.prevent="save" class="space-y-4">
      <AppInput v-model="username" label="Username" placeholder="username" :error="fieldErrors.username || error" autocomplete="username" />
      <AppInput v-model="email" label="Email" placeholder="email@example.com" type="email" :error="fieldErrors.email" autocomplete="email" />
      <AppInput v-model="new_password" label="New password (leave blank to keep)" type="password" placeholder="••••••••" autocomplete="new-password" />
      <label class="flex items-center gap-3 text-sm text-black"><ToggleSwitch v-model="is_staff" /> Staff (admin)</label>
      <label class="flex items-center gap-3 text-sm text-black"><ToggleSwitch v-model="is_active" /> Active</label>
      <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-2 text-xs text-zinc-600">Preview: {{ username || '—' }} • {{ email || 'no email' }} • {{ is_staff ? 'staff' : 'user' }} • {{ is_active ? 'active' : 'inactive' }} • Balance {{ Number(balance || 0).toFixed(2) }}</div>
      <div class="flex gap-2">
        <Button type="submit" :label="loading ? 'Saving...' : 'Save'" :loading="loading" severity="info" />
        <Button label="Cancel" severity="secondary" outlined @click="router.push('/users')" />
      </div>
    </form>

    <section v-if="!fetching" class="mt-6 rounded-lg border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 class="font-semibold text-black">Wallet</h2>
          <p class="text-sm text-zinc-500">Current balance: <span class="font-semibold text-emerald-700">{{ Number(balance || 0).toFixed(2) }}</span></p>
        </div>
      </div>
      <div class="grid gap-3 sm:grid-cols-[120px_1fr]">
        <InputNumber v-model="walletAmount" :min="0.01" :min-fraction-digits="2" :max-fraction-digits="2" placeholder="Amount" fluid />
        <InputText v-model="walletNote" placeholder="Note" class="w-full" />
      </div>
      <div class="mt-3 flex gap-2">
        <Button label="Deposit" size="small" severity="success" :loading="loading" @click="wallet('deposit')" />
        <Button label="Withdraw" size="small" severity="danger" outlined :loading="loading" @click="wallet('withdraw')" />
      </div>

      <DataTable class="mt-4" :value="transactions" data-key="id" size="small" striped-rows show-gridlines>
        <template #empty>No wallet activity yet.</template>
        <Column header="Date" sortable sort-field="created_at">
          <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
        </Column>
        <Column field="kind" header="Type" sortable />
        <Column header="Amount" sortable sort-field="amount" body-class="text-right">
          <template #body="{ data }"><span :class="['font-medium', Number(data.amount) >= 0 ? 'text-emerald-700' : 'text-red-700']">{{ Number(data.amount).toFixed(2) }}</span></template>
        </Column>
        <Column header="Balance" sortable sort-field="balance_after" body-class="text-right">
          <template #body="{ data }">{{ Number(data.balance_after).toFixed(2) }}</template>
        </Column>
        <Column header="Note">
          <template #body="{ data }">{{ data.tournament_name || data.note || '-' }}</template>
        </Column>
      </DataTable>
    </section>
  </div>
</template>
