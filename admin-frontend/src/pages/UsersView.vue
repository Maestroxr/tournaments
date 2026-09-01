<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Tag from 'primevue/tag'
import SearchBar from '@/components/SearchBar.vue'

interface User { id: number; username: string; email: string; is_staff: boolean; is_active: boolean; balance: string }
const users = ref<User[]>([])
const q = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    users.value = await apiFetch<User[]>(`/api/admin/users${qs}`)
  } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Failed' }
  finally { loading.value = false }
}
onMounted(load)
async function remove(id: number) {
  if (!confirm('Delete user?')) return
  try { await apiFetch(`/api/admin/users/${id}`, { method: 'DELETE' }); await load() } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Delete failed' }
}
</script>

<template>
  <div class="mx-auto w-full max-w-5xl">
    <div class="mb-4 flex items-center justify-between gap-3">
      <h1 class="text-2xl font-bold text-black">Users</h1>
      <Button as="router-link" to="/users/new" label="Create User" size="small" severity="info" />
    </div>
    <div class="mb-3"><SearchBar v-model="q" placeholder="Search username..." @search="load" /></div>
    <div v-if="error" class="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{{ error }}</div>
    <DataTable v-else :value="users" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>No users.</template>
      <Column field="id" header="ID" sortable />
      <Column field="username" header="Username" sortable />
      <Column header="Email">
        <template #body="{ data }">{{ data.email || '-' }}</template>
      </Column>
      <Column header="Balance" sortable sort-field="balance">
        <template #body="{ data }"><span class="font-medium text-emerald-700">{{ Number(data.balance || 0).toFixed(2) }}</span></template>
      </Column>
      <Column header="Role">
        <template #body="{ data }"><Tag :value="data.is_staff ? 'staff' : 'user'" :severity="data.is_staff ? 'contrast' : 'secondary'" /></template>
      </Column>
      <Column header="Actions">
        <template #body="{ data }">
          <div class="flex gap-2">
            <Button as="router-link" :to="`/users/${data.id}/edit`" label="Edit" size="small" severity="secondary" outlined />
            <Button label="Delete" size="small" severity="danger" text @click="remove(data.id)" />
          </div>
        </template>
      </Column>
    </DataTable>
  </div>
</template>
