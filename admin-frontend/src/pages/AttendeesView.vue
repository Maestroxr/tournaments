<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch } from '@/services/api'

const route = useRoute()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const participants = ref<any[]>([])
const available = ref<any[]>([])
const q = ref('')
const newName = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    const data = await apiFetch<any>(`/api/admin/tournaments/${id}/attendees${qs}`)
    participants.value = data.participants
    available.value = data.available
  } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Failed' }
  finally { loading.value = false }
}
onMounted(load)

async function addUser(uid: number) {
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees`, { method: 'POST', body: JSON.stringify({ user_id: uid }) }); await load() } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Add failed' }
}
async function addVirtual() {
  if (!newName.value.trim()) return
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees`, { method: 'POST', body: JSON.stringify({ name: newName.value.trim() }) }); newName.value=''; await load() } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Add failed' }
}
async function remove(pid: number) {
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees?participant_id=${pid}`, { method: 'DELETE' }); await load() } catch (e: unknown) { error.value = e instanceof Error ? e.message : 'Remove failed' }
}
</script>

<template>
  <div class="mx-auto w-full max-w-4xl">
    <h1 class="mb-1 text-2xl font-bold text-black">Manage Attendees <span class="text-sm font-normal text-zinc-500">#{{ id }}</span></h1>
    <p class="mb-4 text-sm text-zinc-600">Only when tournament is <span class="font-medium">open</span>. Search users, add virtual names.</p>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else>
      <div v-if="error" class="mb-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{{ error }}</div>

      <div class="mb-6 rounded-lg border border-zinc-200 bg-white p-4">
        <h3 class="mb-2 text-sm font-semibold text-black">Current attendees ({{ participants.length }})</h3>
        <div v-if="participants.length===0" class="text-sm text-zinc-500">No attendees yet.</div>
        <div v-else class="flex flex-wrap gap-2">
          <span v-for="p in participants" :key="p.id" class="inline-flex items-center gap-1 rounded-full border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-black">
            <i :class="p.user_id ? 'bi bi-person-fill' : 'bi bi-person'"></i> {{ p.name }} <button @click="remove(p.id)" class="ml-1 text-red-600 hover:text-red-800">×</button>
          </span>
        </div>
      </div>

      <div class="rounded-lg border border-zinc-200 bg-white p-4">
        <h3 class="mb-2 text-sm font-semibold text-black">Add attendees</h3>
        <div class="mb-3 flex gap-2">
          <input v-model="q" placeholder="Search users..." class="flex-1 rounded border border-zinc-300 px-3 py-2 text-sm text-black" @keydown.enter="load" />
          <button @click="load" class="rounded bg-zinc-900 px-3 py-2 text-sm text-white">Search</button>
        </div>
        <div class="mb-4 flex flex-wrap gap-2">
          <button v-for="u in available" :key="u.id" @click="addUser(u.id)" class="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-100">{{ u.username }}</button>
          <span v-if="available.length===0" class="text-xs text-zinc-500">No users found. Try different search.</span>
        </div>
        <div class="flex gap-2">
          <input v-model="newName" placeholder="Virtual attendee name (one per line in Django, here one at a time)" class="flex-1 rounded border border-zinc-300 px-3 py-2 text-sm text-black" @keydown.enter="addVirtual" />
          <button @click="addVirtual" class="rounded bg-zinc-900 px-3 py-2 text-sm text-white">Add virtual</button>
        </div>
      </div>

      <div class="mt-4"><RouterLink :to="`/tournaments/${id}`" class="text-sm text-zinc-600 hover:underline">← Back to tournament</RouterLink></div>
    </div>
  </div>
</template>
