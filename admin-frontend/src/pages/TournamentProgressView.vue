<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import AppAlert from '@/components/AppAlert.vue'
import TournamentFixtureCard from '@/components/TournamentFixtureCard.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import type { TournamentProgressData } from '@/types/tournamentProgress'

const route = useRoute()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const data = ref<TournamentProgressData | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  error.value = ''
  try { data.value = await apiFetch<TournamentProgressData>(`/api/admin/tournaments/${id}/progress`) } catch (e: unknown) { error.value = formatApiError(e) } finally { loading.value = false }
}

onMounted(() => {
  void load()
  refreshTimer = setInterval(() => {
    if (!loading.value) void load()
  }, 5000)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <header v-if="data?.tournament" class="mb-5">
      <RouterLink :to="`/tournaments/${id}`" class="mb-2 inline-block text-sm text-zinc-600 hover:text-black hover:underline">← Tournament details</RouterLink>
      <div class="flex flex-wrap items-center gap-2">
        <h1 class="text-2xl font-bold text-black">{{ data.tournament.name }}</h1>
        <TournamentStatusBadge :state="data.tournament.state" />
      </div>
      <p class="mt-1 text-sm text-zinc-500">Results are received automatically from completed games. This page refreshes every 5 seconds.</p>
    </header>
    <h1 v-else class="mb-5 text-2xl font-bold text-black">Tournament Progress</h1>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" class="mb-3" />
    <div v-else-if="data" class="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div class="lg:col-span-1">
        <aside class="rounded-xl border border-zinc-200 bg-white p-5 text-sm lg:sticky lg:top-4">
          <div class="text-xs font-medium uppercase tracking-wide text-zinc-500">Tournament</div>
          <div class="mt-1 font-semibold text-black">{{ data.tournament.name }}</div>
          <div class="mt-1 text-xs text-zinc-500">Tournament #{{ data.tournament.id }}</div>
          <div class="mt-4 border-t border-zinc-100 pt-4">
            <div class="text-xs text-zinc-500">Registered players</div>
            <div class="mt-1 font-medium text-zinc-800">{{ data.tournament.participant_count }}</div>
          </div>
          <div v-if="data.is_finished && data.podium?.length" class="mt-3">
            <div class="text-xs font-semibold text-black">Final standings</div>
            <ol class="mt-2 space-y-1">
              <li v-for="(p, idx) in data.podium" :key="p.id" class="text-xs"><span :class="{'text-amber-600': idx===0, 'text-zinc-500': idx===1, 'text-amber-800': idx===2}">{{ idx===0 ? '🥇' : idx===1 ? '🥈' : '🥉' }} {{ p.name }}</span></li>
            </ol>
          </div>
        </aside>
      </div>
      <div class="lg:col-span-2 space-y-4">
        <section v-for="(stageInfo, stageId) in data.stages" :key="String(stageId)" class="rounded-xl border border-zinc-200 bg-white p-5">
          <h2 class="mb-4 text-base font-semibold text-black">{{ String(stageId) }}</h2>
          <div v-for="(level, lidx) in stageInfo.levels" :key="lidx" class="mb-4 last:mb-0">
            <h3 class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Round {{ Number(lidx) + 1 }}<span v-if="level.name"> · {{ level.name }}</span></h3>
            <div class="space-y-2">
              <TournamentFixtureCard v-for="fixture in level.fixtures" :key="fixture.id" :fixture="fixture" />
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
