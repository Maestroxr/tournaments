<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import AppAlert from '@/components/AppAlert.vue'
import TournamentFixtureCard from '@/components/TournamentFixtureCard.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import Button from 'primevue/button'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'

const route = useRoute()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const data = ref<TournamentProgressData | null>(null)
const refreshing = ref(false)
const lastUpdatedAt = ref<Date | null>(null)
const liveConnected = ref(false)
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let socket: WebSocket | null = null

async function load(initial = false) {
  if (initial) loading.value = true
  else refreshing.value = true
  try {
    data.value = await apiFetch<TournamentProgressData>(`/api/admin/tournaments/${id}/progress`)
    error.value = ''
    lastUpdatedAt.value = new Date()
  } catch (e: unknown) {
    error.value = formatApiError(e)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function scheduleRefresh() {
  if (data.value?.is_finished) return
  refreshTimer = setTimeout(async () => {
    await load()
    scheduleRefresh()
  }, 15000)
}

function progressSocketUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/tournaments-ws/admin/tournaments/${id}/progress/`
}

function findFixture(fixtureId: number): TournamentFixture | null {
  if (!data.value) return null
  for (const stage of Object.values(data.value.stages)) {
    for (const level of stage.levels) {
      const fixture = level.fixtures.find((item) => item.id === fixtureId)
      if (fixture) return fixture
    }
  }
  return null
}

function applyLiveSnapshot(payload: unknown) {
  if (!payload || typeof payload !== 'object') return
  const event = payload as { type?: string; fixture_id?: number; live?: TournamentFixture['live'] }
  if (event.type !== 'live_snapshot' || typeof event.fixture_id !== 'number') return
  const fixture = findFixture(event.fixture_id)
  if (!fixture) {
    void load()
    return
  }
  fixture.live = event.live ?? null
  lastUpdatedAt.value = new Date()
}

function closeSocket() {
  if (reconnectTimer !== null) clearTimeout(reconnectTimer)
  reconnectTimer = null
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
}

function connectLiveSocket() {
  if (data.value?.is_finished) return
  closeSocket()
  socket = new WebSocket(progressSocketUrl())
  socket.onopen = () => {
    liveConnected.value = true
  }
  socket.onmessage = (event) => {
    try {
      applyLiveSnapshot(JSON.parse(event.data))
    } catch {
      // Ignore malformed frames; the HTTP fallback will resync the view.
    }
  }
  socket.onclose = () => {
    liveConnected.value = false
    socket = null
    if (!data.value?.is_finished) {
      reconnectTimer = setTimeout(connectLiveSocket, 2500)
    }
  }
  socket.onerror = () => {
    socket?.close()
  }
}

function formatUpdatedAt(value: Date | null) {
  if (!value) return 'Not synced yet'
  return value.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onMounted(async () => {
  await load(true)
  connectLiveSocket()
  scheduleRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) clearTimeout(refreshTimer)
  closeSocket()
})
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <header v-if="data?.tournament" class="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <RouterLink :to="`/tournaments/${id}`" class="mb-2 inline-flex items-center text-sm text-zinc-600 hover:text-black hover:underline"><i class="bi bi-arrow-left mr-1" aria-hidden="true"></i>Tournament details</RouterLink>
        <div class="flex flex-wrap items-center gap-2">
          <h1 class="text-2xl font-bold text-black">{{ data.tournament.name }}</h1>
          <TournamentStatusBadge :state="data.tournament.state" />
        </div>
        <p class="mt-1 text-sm text-zinc-500">
          {{ data.is_finished ? 'Final results are saved from confirmed tournament matches.' : 'Match results sync automatically while the tournament is active.' }}
        </p>
      </div>
      <div class="flex items-center gap-3 text-xs text-zinc-500">
        <span class="inline-flex items-center gap-1.5">
          <span :class="['h-2 w-2 rounded-full', liveConnected ? 'bg-emerald-500' : 'bg-zinc-300']"></span>
          {{ liveConnected ? 'Live connected' : 'Live reconnecting' }}
        </span>
        <span class="inline-flex items-center gap-1.5"><i :class="['bi bi-arrow-repeat', refreshing && 'animate-spin']" aria-hidden="true"></i>{{ data.is_finished ? 'Finalized' : 'Synced' }} {{ formatUpdatedAt(lastUpdatedAt) }}</span>
        <Button icon="bi bi-arrow-clockwise" text rounded severity="secondary" aria-label="Refresh results" :loading="refreshing" @click="load()" />
      </div>
    </header>
    <h1 v-else class="mb-5 text-2xl font-bold text-black">Tournament Results</h1>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" class="mb-3" />
    <div v-else-if="data" class="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div class="lg:col-span-1">
        <aside class="rounded-lg border border-zinc-200 bg-white p-5 text-sm lg:sticky lg:top-4">
          <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Tournament overview</p>
          <p class="mt-1 font-semibold text-black">{{ data.tournament.name }}</p>
          <p class="mt-1 text-xs text-zinc-500">Tournament #{{ data.tournament.id }}</p>
          <div class="mt-4 grid grid-cols-2 border-y border-zinc-100 py-3">
            <div>
              <p class="text-xs text-zinc-500">Players</p>
              <p class="mt-1 text-lg font-bold text-black">{{ data.tournament.participant_count }}</p>
            </div>
            <div class="border-l border-zinc-100 pl-3">
              <p class="text-xs text-zinc-500">Status</p>
              <p class="mt-1 font-semibold text-zinc-800">{{ data.is_finished ? 'Complete' : 'Live' }}</p>
            </div>
          </div>
          <div v-if="data.is_finished && data.podium?.length" class="mt-4">
            <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Final standings</p>
            <ol class="mt-2 divide-y divide-zinc-100 border-y border-zinc-100">
              <li v-for="(p, idx) in data.podium" :key="p.id" class="flex items-center gap-2 py-2 text-sm">
                <span :class="['inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold', idx === 0 ? 'bg-amber-100 text-amber-800' : 'bg-zinc-100 text-zinc-600']">{{ idx + 1 }}</span>
                <span :class="idx === 0 ? 'font-semibold text-black' : 'text-zinc-700'">{{ p.name }}</span>
              </li>
            </ol>
          </div>
        </aside>
      </div>
      <div class="lg:col-span-2 space-y-4">
        <section v-for="(stageInfo, stageId) in data.stages" :key="String(stageId)" class="rounded-lg border border-zinc-200 bg-white p-5">
          <div class="mb-4 flex items-center gap-3">
            <span class="inline-flex h-8 w-8 items-center justify-center rounded-full bg-zinc-900 text-sm font-semibold text-white">{{ Object.keys(data.stages).indexOf(String(stageId)) + 1 }}</span>
            <h2 class="text-base font-semibold text-black">{{ String(stageId) }}</h2>
          </div>
          <div v-for="(level, lidx) in stageInfo.levels" :key="lidx" class="mb-4 last:mb-0">
            <h3 class="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase">Round {{ Number(lidx) + 1 }}<span v-if="level.name"> / {{ level.name }}</span></h3>
            <div class="space-y-2">
              <TournamentFixtureCard v-for="fixture in level.fixtures" :key="fixture.id" :fixture="fixture" />
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
