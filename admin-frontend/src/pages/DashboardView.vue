<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '@/services/api'

interface Dashboard {
  total_tournaments: number
  total_users: number
  total_participants: number
  counts: { drafts: number; open: number; active: number; finished: number }
  recent_tournaments: { id: number; name: string; published: boolean }[]
  recent_users: { id: number; username: string; email: string; is_staff: boolean }[]
}
const data = ref<Dashboard | null>(null)
const loading = ref(true)
const error = ref('')
onMounted(async () => {
  try { data.value = await apiFetch<Dashboard>('/api/admin/dashboard') } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Failed' } finally { loading.value = false }
})
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <h1 class="mb-1 text-2xl font-bold text-black">Dashboard</h1>
    <p class="mb-6 text-sm text-zinc-600">Overview — tournaments & users</p>

    <div v-if="loading" class="py-8 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else-if="error" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ error }}</div>
    <div v-else-if="data" class="space-y-6">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div class="rounded-lg border border-zinc-200 bg-white p-4"><div class="text-xs text-zinc-500">Total tournaments</div><div class="text-2xl font-bold text-black">{{ data.total_tournaments }}</div></div>
        <div class="rounded-lg border border-zinc-200 bg-white p-4"><div class="text-xs text-zinc-500">Total users</div><div class="text-2xl font-bold text-black">{{ data.total_users }}</div></div>
        <div class="rounded-lg border border-zinc-200 bg-white p-4"><div class="text-xs text-zinc-500">Total participants</div><div class="text-2xl font-bold text-black">{{ data.total_participants }}</div></div>
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-3"><div class="text-xs text-zinc-500">Drafts</div><div class="text-xl font-bold text-black">{{ data.counts.drafts }}</div></div>
        <div class="rounded-lg border border-zinc-200 bg-emerald-50 p-3"><div class="text-xs text-zinc-500">Open</div><div class="text-xl font-bold text-emerald-700">{{ data.counts.open }}</div></div>
        <div class="rounded-lg border border-zinc-200 bg-amber-50 p-3"><div class="text-xs text-zinc-500">Active</div><div class="text-xl font-bold text-amber-700">{{ data.counts.active }}</div></div>
        <div class="rounded-lg border border-zinc-200 bg-zinc-900 p-3"><div class="text-xs text-zinc-300">Finished</div><div class="text-xl font-bold text-white">{{ data.counts.finished }}</div></div>
      </div>
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div class="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 class="mb-2 text-sm font-semibold text-black">Recent tournaments</h3>
          <ul class="space-y-1 text-sm">
            <li v-for="t in data.recent_tournaments" :key="t.id" class="flex justify-between"><RouterLink :to="`/tournaments/${t.id}`" class="text-black hover:underline">{{ t.name }}</RouterLink><span :class="['text-xs', t.published ? 'text-emerald-600' : 'text-zinc-500']">{{ t.published ? 'published' : 'draft' }}</span></li>
            <li v-if="data.recent_tournaments.length===0" class="text-xs text-zinc-500">No tournaments.</li>
          </ul>
        </div>
        <div class="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 class="mb-2 text-sm font-semibold text-black">Recent users</h3>
          <ul class="space-y-1 text-sm">
            <li v-for="u in data.recent_users" :key="u.id" class="flex justify-between"><RouterLink :to="`/users/${u.id}/edit`" class="text-black hover:underline">{{ u.username }}</RouterLink><span :class="['text-xs', u.is_staff ? 'text-zinc-900 font-medium' : 'text-zinc-500']">{{ u.is_staff ? 'staff' : 'user' }}</span></li>
            <li v-if="data.recent_users.length===0" class="text-xs text-zinc-500">No users.</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>
