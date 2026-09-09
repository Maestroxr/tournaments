<script setup lang="ts">
import { computed, ref, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch, ApiError, formatApiError } from '@/services/api'
import AppAlert from '@/components/AppAlert.vue'
import TournamentMatchSummary from '@/components/tournament/TournamentMatchSummary.vue'
import TournamentMatchesPanel from '@/components/tournament/TournamentMatchesPanel.vue'
import TournamentStandingsPanel from '@/components/tournament/TournamentStandingsPanel.vue'
import TournamentMatchDialog from '@/components/tournament/TournamentMatchDialog.vue'
import TournamentLiveAttention from '@/components/tournament/TournamentLiveAttention.vue'
import TournamentLiveMatchGroup from '@/components/tournament/TournamentLiveMatchGroup.vue'
import { useI18n } from '@/i18n'
import { useTournamentWorkspace } from '@/composables/useTournamentWorkspace'
import Button from 'primevue/button'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const workspace = useTournamentWorkspace()
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
let disposed = false
let refreshQueued = false
const selectedView = computed(() => {
  if (route.name === 'tournament-bracket') return 'matches'
  if (route.name === 'tournament-standings' || route.name === 'tournament-results') return 'standings'
  return 'live'
})
const fixtures = computed(() => Object.values(data.value?.stages ?? {}).flatMap(stage => stage.levels.flatMap(level => level.fixtures)))
const selectedFixtureId = ref<number | null>(null)
const selectedFixture = computed(() => fixtures.value.find(f => f.id === selectedFixtureId.value))
const selectedRound = computed(() => {
  for (const stage of Object.values(data.value?.stages ?? {})) {
    const index = stage.levels.findIndex(level => level.fixtures.some(f => f.id === selectedFixtureId.value))
    if (index >= 0) return stage.levels[index]?.name || t('tournamentWorkspace.round', { count: index + 1 })
  }
  return ''
})
const selectedSources = computed(() => {
  const sources: Partial<Record<1 | 2, TournamentFixture>> = {}
  for (const fixture of fixtures.value) {
    const target = fixture.bracket?.winner_to
    if (target?.fixture_id === selectedFixtureId.value && (target.player_slot === 1 || target.player_slot === 2)) sources[target.player_slot] = fixture
  }
  return sources
})
type OperationalStatus = NonNullable<TournamentFixture['operational_status']>

function operationalStatus(fixture: TournamentFixture): OperationalStatus {
  if (fixture.operational_status) return fixture.operational_status
  if (fixture.is_confirmed) return 'completed'
  if (fixture.score1 != null || fixture.score2 != null || fixture.confirmations > 0) return 'review'
  if (fixture.live?.status === 'playing') return 'playing'
  if (fixture.player1 && fixture.player2) return 'waiting'
  if (fixture.player1 || fixture.player2) return 'waiting_opponent'
  return 'upcoming'
}

const byStatus = (status: OperationalStatus) => computed(() =>
  fixtures.value.filter(fixture => operationalStatus(fixture) === status),
)
const playingMatches = byStatus('playing')
const stalledMatches = byStatus('stalled')
const reviewMatches = byStatus('review')
const waitingMatches = byStatus('waiting')
const upcomingMatches = computed(() => fixtures.value
  .filter(fixture => operationalStatus(fixture) === 'upcoming' && (fixture.player1 || fixture.player2))
  .slice(0, 4))
const completedRoundMatches = computed(() => fixtures.value.filter(fixture =>
  operationalStatus(fixture) === 'completed' && (fixture.is_current_round ?? true),
))
const waitingPlayers = computed(() => data.value?.control_room?.waiting_players ?? fixtures.value
  .filter(fixture => operationalStatus(fixture) === 'waiting_opponent')
  .flatMap((fixture) => {
    const player = fixture.player1 || fixture.player2
    return player?.id == null ? [] : [{
      id: player.id,
      name: player.name || player.username || '',
      user_id: player.user_id,
      fixture_id: fixture.id,
      round_name: fixture.round_name || '',
    }]
  }))

watch(selectedView, () => { selectedFixtureId.value = null })

async function load(initial = false) {
  if (disposed) return
  if (refreshing.value) { refreshQueued = true; return }
  refreshing.value = true
  if (initial) loading.value = true
  else refreshing.value = true
  try {
    const previousState = data.value?.tournament.state
    const previousLifecycleState = data.value?.tournament.lifecycle_state
    const result = await apiFetch<TournamentProgressData>(`/api/admin/tournaments/${id}/progress`)
    if (disposed) return
    data.value = result
    if (!initial && (previousState !== result.tournament.state || previousLifecycleState !== result.tournament.lifecycle_state)) {
      await workspace?.refresh()
    }
    if (result.is_finished) closeSocket()
    error.value = ''
    lastUpdatedAt.value = new Date()
  } catch (e: unknown) {
    if (disposed) return
    if (e instanceof ApiError && e.status === 412) {
      await router.replace({ name: 'tournament-detail', params: { id } })
      return
    }
    error.value = formatApiError(e)
  } finally {
    loading.value = false
    refreshing.value = false
    if (refreshQueued && !disposed) { refreshQueued = false; void load() }
  }
}

function scheduleRefresh() {
  if (disposed || data.value?.is_finished) return
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
  const previousStatus = operationalStatus(fixture)
  fixture.live = event.live ?? null
  if (!fixture.is_confirmed && fixture.score1 == null && fixture.score2 == null && event.live?.status === 'playing') {
    fixture.operational_status = 'playing'
    fixture.stalled = false
    fixture.last_activity_at = new Date().toISOString()
    fixture.started_at ||= fixture.last_activity_at
    fixture.duration_seconds ||= 0
    if (data.value?.control_room && previousStatus !== 'playing') {
      data.value.control_room.counts[previousStatus] = Math.max(0, data.value.control_room.counts[previousStatus] - 1)
      data.value.control_room.counts.playing += 1
    }
  } else if (event.live?.status === 'completed') {
    void load()
  }
  lastUpdatedAt.value = new Date()
}

function closeSocket() {
  liveConnected.value = false
  if (reconnectTimer !== null) clearTimeout(reconnectTimer)
  reconnectTimer = null
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
}

function connectLiveSocket() {
  if (disposed || !data.value || data.value.is_finished) return
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
    if (!disposed && !data.value?.is_finished) {
      reconnectTimer = setTimeout(connectLiveSocket, 2500)
    }
  }
  socket.onerror = () => {
    socket?.close()
  }
}

function formatUpdatedAt(value: Date | null) {
  if (!value) return t('tournamentWorkspace.notSynced')
  return value.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onMounted(async () => {
  await load(true)
  connectLiveSocket()
  scheduleRefresh()
})

onBeforeUnmount(() => {
  disposed = true
  if (refreshTimer !== null) clearTimeout(refreshTimer)
  closeSocket()
})
</script>

<template>
  <div class="tournament-progress-page min-w-0">
      <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">{{ t('common.loading') }}</div>
      <AppAlert v-if="error" type="error" :message="error" class="mb-3" />
      <Button v-if="!loading && !data" :label="t('common.refresh')" severity="secondary" outlined :loading="refreshing" @click="load()" />

      <template v-if="data">
        <div class="workspace-toolbar">
          <h2>{{ t(`tournamentWorkspace.${selectedView}`) }}</h2>
          <div class="flex flex-wrap items-center gap-3 text-xs text-zinc-500" role="status">
            <span v-if="!data.is_finished" class="inline-flex items-center gap-1.5">
              <span :class="['h-2 w-2 rounded-full', liveConnected ? 'bg-emerald-500' : 'bg-zinc-300']"></span>
              {{ t(liveConnected ? 'tournamentWorkspace.connected' : 'tournamentWorkspace.reconnecting') }}
            </span>
            <span>{{ t(data.is_finished ? 'tournamentWorkspace.finalized' : 'tournamentWorkspace.synced') }} {{ formatUpdatedAt(lastUpdatedAt) }}</span>
            <Button icon="bi bi-arrow-clockwise" text rounded severity="secondary" :aria-label="t('common.refresh')" :loading="refreshing" :disabled="refreshing" @click="load()" />
          </div>
        </div>

        <template v-if="selectedView === 'live'">
          <TournamentMatchSummary
            :fixtures="fixtures"
            :players="data.tournament.participant_count"
            :control-room="data.control_room"
          />
          <TournamentLiveAttention
            :stalled="stalledMatches"
            :review="reviewMatches"
            :waiting-players="waitingPlayers"
            @select="selectedFixtureId = $event"
          />
          <section class="mt-6">
            <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 class="text-base font-semibold text-slate-100">{{ t(data.is_finished ? 'tournamentWorkspace.tournamentFinished' : 'controlRoom.matchFlow') }}</h3>
              <Button as="router-link" :to="{ name: data.is_finished ? 'tournament-results' : 'tournament-bracket', params: { id } }" :label="t(data.is_finished ? 'tournamentWorkspace.standings' : 'tournamentWorkspace.allMatches')" severity="secondary" outlined size="small" />
            </div>
            <p class="mb-4 text-sm text-zinc-500">{{ t(data.is_finished ? 'tournamentWorkspace.finishedHint' : 'controlRoom.matchFlowHint') }}</p>
            <div v-if="!data.is_finished" class="live-groups">
              <TournamentLiveMatchGroup
                :title="t('controlRoom.playingTitle')" :hint="t('controlRoom.playingHint')"
                :fixtures="playingMatches" :empty="t('controlRoom.playingEmpty')" tone="playing"
                @select="selectedFixtureId = $event"
              />
              <TournamentLiveMatchGroup
                :title="t('controlRoom.waitingTitle')" :hint="t('controlRoom.waitingHint')"
                :fixtures="waitingMatches" :empty="t('controlRoom.waitingEmpty')"
                @select="selectedFixtureId = $event"
              />
              <TournamentLiveMatchGroup
                :title="t('controlRoom.upcomingTitle')" :hint="t('controlRoom.upcomingHint')"
                :fixtures="upcomingMatches" :empty="t('controlRoom.upcomingEmpty')"
                @select="selectedFixtureId = $event"
              />
              <TournamentLiveMatchGroup
                :title="t('controlRoom.completedTitle')" :hint="t('controlRoom.completedHint')"
                :fixtures="completedRoundMatches" :empty="t('controlRoom.completedEmpty')" tone="complete"
                @select="selectedFixtureId = $event"
              />
            </div>
          </section>
        </template>
        <TournamentMatchesPanel v-else-if="selectedView === 'matches'" :stages="data.stages" @select="selectedFixtureId = $event" />
        <TournamentStandingsPanel v-else :finished="data.is_finished" :podium="data.podium || []" />
        <TournamentMatchDialog v-if="selectedFixture" :key="selectedFixture.id" :fixture="selectedFixture"
          :tournament-id="id" :round="selectedRound" :sources="selectedSources" :live-connected="liveConnected" :updated-at="lastUpdatedAt" @saved="load()" @close="selectedFixtureId = null" />
      </template>
  </div>
</template>

<style scoped>
.workspace-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 22px 0; }
.workspace-toolbar h2 { color: #eaf2ff; font-size: 21px; font-weight: 650; }
.live-groups { display: grid; gap: 14px; }
</style>
