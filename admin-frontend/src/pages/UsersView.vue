<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Tag from 'primevue/tag'
import SearchBar from '@/components/SearchBar.vue'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

interface User { id: number; username: string; email: string; is_staff: boolean; is_active: boolean; balance: string }
const users = ref<User[]>([])
const q = ref('')
const loading = ref(false)
const error = ref('')
const { t } = useI18n()

async function load() {
  loading.value = true
  error.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    users.value = await apiFetch<User[]>(`/api/admin/users${qs}`)
  } catch (e: unknown) { error.value = formatApiError(e) }
  finally { loading.value = false }
}
onMounted(load)
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
    <div class="mb-3"><SearchBar v-model="q" :placeholder="t('users.search')" @search="load" /></div>
    <AppAlert v-if="error" class="mb-3" type="error" :message="error" dismissible @close="error = ''" />
    <DataTable v-else :value="users" :loading="loading" data-key="id" striped-rows show-gridlines size="small">
      <template #empty>{{ t('users.empty') }}</template>
      <Column field="id" :header="t('common.id')" sortable />
      <Column field="username" :header="t('users.username')" sortable />
      <Column :header="t('users.email')">
        <template #body="{ data }">{{ data.email || '-' }}</template>
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
