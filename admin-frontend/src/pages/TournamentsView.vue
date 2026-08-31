<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { apiFetch } from '@/services/api'
import TournamentCard from '@/components/TournamentCard.vue'
import SearchBar from '@/components/SearchBar.vue'

interface Tournament {
  id: number
  name: string
  state: string
  creator: string | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
}
const tournaments = ref<Tournament[]>([])
const q = ref('')
const stateFilter = ref<string>('all')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (q.value.trim()) params.set('q', q.value.trim())
    const qs = params.toString()
    tournaments.value = await apiFetch<Tournament[]>(`/api/admin/tournaments${qs ? `?${qs}` : ''}`)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load'
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(stateFilter, () => {}) // filter is client-side

const filtered = computed(() => {
  if (stateFilter.value === 'all') return tournaments.value
  return tournaments.value.filter((t) => t.state === stateFilter.value)
})

const states = ['all', 'draft', 'open', 'active', 'finished'] as const
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-2xl font-bold text-black">Tournaments</h1>
      <RouterLink to="/tournaments/new" class="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">Create Tournament</RouterLink>
    </div>

    <div class="mb-4 flex flex-wrap gap-3">
      <div class="flex-1 min-w-[240px]"><SearchBar v-model="q" placeholder="Search by name..." @search="load" /></div>
      <select v-model="stateFilter" class="rounded border border-zinc-300 bg-white px-3 py-2 text-sm text-black">
        <option v-for="s in states" :key="s" :value="s">{{ s === 'all' ? 'All states' : s }}</option>
      </select>
    </div>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else-if="error" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ error }}</div>
    <div v-else-if="filtered.length === 0" class="py-10 text-center text-sm text-zinc-500">No tournaments. <RouterLink to="/tournaments/new" class="text-emerald-600 hover:underline">Create one</RouterLink></div>
    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <TournamentCard v-for="t in filtered" :key="t.id" :tournament="t" />
    </div>
  </div>
</template>
