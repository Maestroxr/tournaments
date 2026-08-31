<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '@/services/api'
import SearchBar from '@/components/SearchBar.vue'
import { RouterLink } from 'vue-router'

interface User { id: number; username: string; email: string; is_staff: boolean; is_active: boolean }
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
      <RouterLink to="/users/new" class="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">Create User</RouterLink>
    </div>
    <div class="mb-3"><SearchBar v-model="q" placeholder="Search username..." @search="load" /></div>
    <div v-if="loading" class="py-8 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else-if="error" class="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{{ error }}</div>
    <div v-else class="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-zinc-50 text-xs text-zinc-600"><tr><th class="px-3 py-2 text-left">ID</th><th class="px-3 py-2 text-left">Username</th><th class="px-3 py-2 text-left">Email</th><th class="px-3 py-2 text-left">Staff</th><th class="px-3 py-2 text-left">Actions</th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" class="border-t border-zinc-200">
            <td class="px-3 py-2 text-black">{{ u.id }}</td>
            <td class="px-3 py-2 font-medium text-black">{{ u.username }}</td>
            <td class="px-3 py-2 text-zinc-600">{{ u.email || '—' }}</td>
            <td class="px-3 py-2"><span :class="['rounded px-1.5 py-0.5 text-xs', u.is_staff ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600']">{{ u.is_staff ? 'staff' : 'user' }}</span></td>
            <td class="px-3 py-2"><div class="flex gap-1"><RouterLink :to="`/users/${u.id}/edit`" class="rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-black hover:bg-zinc-50">Edit</RouterLink><button @click="remove(u.id)" class="rounded bg-red-50 px-2 py-1 text-xs text-red-600 hover:bg-red-100">Delete</button></div></td>
          </tr>
          <tr v-if="users.length===0"><td colspan="5" class="px-3 py-8 text-center text-sm text-zinc-500">No users.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
