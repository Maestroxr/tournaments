<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Tag from 'primevue/tag'
import SearchBar from '@/components/SearchBar.vue'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

interface User { id: number; username: string; phone_number: string; is_staff: boolean; is_active: boolean; balance: string }
const users = ref<User[]>([])
const q = ref('')
const loading = ref(false)
const error = ref('')
const { t } = useI18n()
let loadRequestId = 0
let lastPageRefreshAt = 0

async function load(silent = false) {
  const requestId = ++loadRequestId
  if (!silent) loading.value = true
  if (error.value) error.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    const next = await apiFetch<User[]>(`/api/admin/users${qs}`)
    if (requestId === loadRequestId && JSON.stringify(users.value) !== JSON.stringify(next)) {
      users.value = next
    }
  } catch (e: unknown) {
    if (requestId === loadRequestId) error.value = formatApiError(e)
  } finally {
    if (requestId === loadRequestId) loading.value = false
  }
}

function refreshWhenPageReturns() {
  if (document.visibilityState === 'hidden') return
  const now = Date.now()
  if (now - lastPageRefreshAt < 500) return
  lastPageRefreshAt = now
  void load(true)
}

onMounted(() => {
  lastPageRefreshAt = Date.now()
  void load()
  window.addEventListener('focus', refreshWhenPageReturns)
  document.addEventListener('visibilitychange', refreshWhenPageReturns)
})
onBeforeUnmount(() => {
  loadRequestId += 1
  window.removeEventListener('focus', refreshWhenPageReturns)
  document.removeEventListener('visibilitychange', refreshWhenPageReturns)
})
async function remove(id: number) {
  if (!confirm(t('users.deleteConfirm'))) return
  try { await apiFetch(`/api/admin/users/${id}`, { method: 'DELETE' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
</script>

<template>
  <div class="mx-auto w-full max-w-5xl">
    <div class="mb-4 flex items-center justify-between gap-3">
      <h1 class="text-2xl font-bold text-black">{{ t('users.title') }}</h1>
      <Button as="router-link" to="/users/new" :label="t('users.createTitle')" size="small" severity="info" />
    </div>
    <div class="mb-3"><SearchBar v-model="q" :placeholder="t('users.search')" @search="load()" /></div>
    <AppAlert v-if="error" class="mb-3" type="error" :message="error" dismissible @close="error = ''" />
    <DataTable v-else :value="users" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>{{ t('users.empty') }}</template>
      <Column field="id" :header="t('common.id')" sortable />
      <Column field="username" :header="t('users.username')" sortable />
      <Column :header="t('users.phone')">
        <template #body="{ data }">{{ data.phone_number || '-' }}</template>
      </Column>
      <Column :header="t('users.balance')" sortable sort-field="balance">
        <template #body="{ data }"><span class="font-medium text-emerald-700">{{ Number(data.balance || 0).toFixed(2) }}</span></template>
      </Column>
      <Column :header="t('users.role')">
        <template #body="{ data }"><Tag :value="data.is_staff ? t('common.staff') : t('common.user')" :severity="data.is_staff ? 'contrast' : 'secondary'" /></template>
      </Column>
      <Column :header="t('common.actions')">
        <template #body="{ data }">
          <div class="flex gap-2">
            <Button as="router-link" :to="`/users/${data.id}/edit`" :label="t('common.edit')" size="small" severity="secondary" outlined />
            <Button :label="t('common.delete')" size="small" severity="danger" text @click="remove(data.id)" />
          </div>
        </template>
      </Column>
    </DataTable>
  </div>
</template>
