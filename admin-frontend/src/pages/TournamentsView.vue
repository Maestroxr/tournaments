<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import Select from 'primevue/select'
import FinishedTournamentCard from '@/components/FinishedTournamentCard.vue'
import TournamentCard from '@/components/TournamentCard.vue'
import SearchBar from '@/components/SearchBar.vue'
import AppAlert from '@/components/AppAlert.vue'
import { tournamentStateFilterLabel } from '@/utils/adminLabels'

interface Tournament {
  id: number
  name: string
  state: string
  creator: string | null
  creator_id: number | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
  doubling_enabled: boolean
  entry_fee: string
  prize_money: string
  champion?: {
    id: number | string
    name: string
    position: number
  } | null
  podium?: {
    id: number | string
    name: string
    position: number
  }[]
}
const route = useRoute()
const tournaments = ref<Tournament[]>([])
const q = ref('')
const states = ['current', 'all', 'draft', 'open', 'active', 'finished'] as const
type TournamentStateFilter = typeof states[number]
const stateOptions = states.map((state) => ({ value: state, label: tournamentStateFilterLabel(state) }))
const requestedState = String(route.query.state ?? 'current')
const stateFilter = ref<TournamentStateFilter>(
  states.includes(requestedState as TournamentStateFilter) ? requestedState as TournamentStateFilter : 'current',
)
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
    error.value = formatApiError(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(stateFilter, () => {}) // filter is client-side
watch(
  () => route.query.state,
  (state) => {
    const next = String(state ?? 'current')
    stateFilter.value = states.includes(next as TournamentStateFilter)
      ? (next as TournamentStateFilter)
      : 'current'
  },
)

const filtered = computed(() => {
  let result = tournaments.value
  if (stateFilter.value === 'current') {
    result = result.filter((t) => t.state !== 'finished')
  } else if (stateFilter.value !== 'all') {
    result = result.filter((t) => t.state === stateFilter.value)
  }

  const view = String(route.query.view ?? '')
  if (view === 'waiting') {
    result = result.filter((t) => t.state === 'open' && t.participant_count < t.min_players)
  }
  if (view === 'upcoming') {
    const parsedDays = Number(route.query.days ?? 7)
    const days = [1, 7, 30].includes(parsedDays) ? parsedDays : 7
    const now = Date.now()
    const end = now + days * 24 * 60 * 60 * 1000
    result = result.filter((t) => {
      if (t.state !== 'open' || !t.starts_at) return false
      const startsAt = new Date(t.starts_at).getTime()
      return startsAt >= now && startsAt <= end
    })
  }
  return result
})

const filteredLabel = computed(() => {
  if (route.query.view === 'waiting') return 'Waiting for players'
  if (route.query.view === 'upcoming') return `Upcoming in the next ${route.query.days ?? 7} days`
  if (stateFilter.value === 'finished') return 'Tournament history and saved results'
  return ''
})

</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div><h1 class="text-2xl font-bold text-black">Tournaments</h1><p v-if="filteredLabel" class="mt-1 text-sm text-zinc-500">{{ filteredLabel }}</p></div>
      <Button as="router-link" to="/tournaments/new" label="Create Tournament" severity="success" />
    </div>

    <div class="mb-4 flex flex-wrap gap-3">
      <div class="flex-1 min-w-[240px]"><SearchBar v-model="q" placeholder="Search by name..." @search="load" /></div>
      <Select v-model="stateFilter" :options="stateOptions" option-label="label" option-value="value" class="min-w-48" />
    </div>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <AppAlert v-else-if="error" type="error" :message="error" dismissible @close="error = ''" />
    <div v-else-if="filtered.length === 0" class="py-10 text-center text-sm text-zinc-500">No tournaments. <RouterLink to="/tournaments/new" class="text-emerald-600 hover:underline">Create one</RouterLink></div>
    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <template v-for="t in filtered" :key="t.id">
        <FinishedTournamentCard v-if="t.state === 'finished'" :tournament="t" />
        <TournamentCard v-else :tournament="t" />
      </template>
    </div>
  </div>
</template>
