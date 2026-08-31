<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
const error = ref('')
const loading = ref(false)
const fetching = ref(true)

interface UserDetail {
  id: number
  username: string
  email?: string
  is_staff?: boolean
  is_active?: boolean
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
</script>

<template>
  <div class="mx-auto w-full max-w-lg">
    <h1 class="mb-4 text-2xl font-bold text-black">Edit User</h1>
    <p v-if="fetching" class="text-sm text-zinc-500">Loading…</p>
    <form v-else @submit.prevent="save" class="space-y-4">
      <AppInput v-model="username" label="Username" placeholder="username" :error="fieldErrors.username || error" autocomplete="username" />
      <AppInput v-model="email" label="Email" placeholder="email@example.com" type="email" :error="fieldErrors.email" autocomplete="email" />
      <AppInput v-model="new_password" label="New password (leave blank to keep)" type="password" placeholder="••••••••" autocomplete="new-password" />
      <label class="flex items-center gap-2 text-sm text-black"><input v-model="is_staff" type="checkbox" class="h-4 w-4 rounded border-zinc-300" /> Staff (admin)</label>
      <label class="flex items-center gap-2 text-sm text-black"><input v-model="is_active" type="checkbox" class="h-4 w-4 rounded border-zinc-300" /> Active</label>
      <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-2 text-xs text-zinc-600">Preview: {{ username || '—' }} • {{ email || 'no email' }} • {{ is_staff ? 'staff' : 'user' }} • {{ is_active ? 'active' : 'inactive' }}</div>
      <div class="flex gap-2">
        <button type="submit" :disabled="loading" class="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">{{ loading ? 'Saving…' : 'Save' }}</button>
        <button type="button" class="rounded border border-zinc-300 bg-white px-4 py-2 text-sm text-black hover:bg-zinc-50" @click="router.push('/users')">Cancel</button>
      </div>
    </form>
  </div>
</template>
