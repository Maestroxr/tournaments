<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import SelectButton from 'primevue/selectbutton'
import AppAlert from '@/components/AppAlert.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import UserQuickView from '@/components/UserQuickView.vue'

type RangeDays = 1 | 7 | 30
type Severity = 'critical' | 'warning' | 'info'

interface TournamentSummary {
  id: number
  name: string
  state: string
  starts_at: string | null
  participant_count: number
  min_players: number
  max_players: number | null
}

interface ActiveTournament extends TournamentSummary {
  stage: string
  round: string
  pending_matches: number
}

interface AttentionItem extends TournamentSummary {
  kind: 'overdue' | 'waiting_players' | 'pending_matches' | 'draft'
  severity: Severity
  message: string
  action_label: string
  action_to: string
}

interface KpiValue {
  value: number
  context: string
}

interface DashboardData {
  updated_at: string
  range_days: RangeDays
  kpis: {
    active: KpiValue
    upcoming: KpiValue
    waiting: KpiValue
    pending_matches: KpiValue
    new_users: KpiValue
  }
  counts: { draft: number; open: number; active: number; finished: number }
  attention: AttentionItem[]
  active_tournaments: ActiveTournament[]
  upcoming_tournaments: TournamentSummary[]
  recent_users: {
    id: number
    username: string
    email: string
    is_staff: boolean
    is_active: boolean
  }[]
}

const data = ref<DashboardData | null>(null)
const loading = ref(true)
const error = ref('')
const rangeDays = ref<RangeDays>(7)
const ranges: { value: RangeDays; label: string }[] = [
  { value: 1, label: 'Today' },
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
]

const kpiCards = computed(() => {
  if (!data.value) return []
  return [
    { key: 'active', label: 'Active tournaments', icon: 'bi-play-circle', to: '/tournaments?state=active', ...data.value.kpis.active },
    { key: 'upcoming', label: 'Upcoming tournaments', icon: 'bi-calendar-event', to: `/tournaments?view=upcoming&days=${rangeDays.value}`, ...data.value.kpis.upcoming },
    { key: 'waiting', label: 'Waiting for players', icon: 'bi-people', to: '/tournaments?view=waiting', ...data.value.kpis.waiting },
    { key: 'pending', label: 'Pending matches', icon: 'bi-hourglass-split', to: '/tournaments?state=active', ...data.value.kpis.pending_matches },
    { key: 'users', label: 'New users', icon: 'bi-person-plus', to: '/users', ...data.value.kpis.new_users },
  ]
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiFetch<DashboardData>(`/api/admin/dashboard?days=${rangeDays.value}`)
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

async function selectRange(value: RangeDays) {
  if (rangeDays.value === value) return
  rangeDays.value = value
  await load()
}

function formatDate(value: string | null) {
  if (!value) return 'Not scheduled'
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function formatUpdatedAt(value: string) {
  return new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function severityClass(severity: Severity) {
  if (severity === 'critical') return 'border-red-200 bg-red-50 text-red-700'
  if (severity === 'warning') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-blue-200 bg-blue-50 text-blue-700'
}

function severityIcon(severity: Severity) {
  if (severity === 'critical') return 'bi-exclamation-octagon'
  if (severity === 'warning') return 'bi-exclamation-triangle'
  return 'bi-info-circle'
}

function attentionLabel(kind: AttentionItem['kind']) {
  if (kind === 'overdue') return 'Schedule overdue'
  if (kind === 'waiting_players') return 'Registration'
  if (kind === 'pending_matches') return 'Match result'
  return 'Draft tournament'
}

onMounted(load)
</script>

<template>
  <div class="admin-dashboard mx-auto w-full max-w-6xl">
    <header class="admin-page-header mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-black">Dashboard</h1>
        <p class="mt-1 text-sm text-zinc-600">Tournament operations at a glance</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button as="router-link" to="/users/new" label="Create user" icon="bi bi-person-plus" severity="secondary" outlined />
        <Button as="router-link" to="/tournaments/new" label="Create tournament" icon="bi bi-plus-lg" severity="contrast" />
      </div>
    </header>

    <div class="admin-range-bar mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 bg-white p-2">
      <SelectButton v-model="rangeDays" :options="ranges" option-label="label" option-value="value" aria-label="Dashboard time range" @update:model-value="selectRange($event as RangeDays)" />
      <div class="flex items-center gap-3 px-2 text-xs text-zinc-500">
        <span v-if="data">Updated at {{ formatUpdatedAt(data.updated_at) }}</span>
        <Button label="Refresh" icon="bi bi-arrow-clockwise" size="small" severity="secondary" text :loading="loading" @click="load" />
      </div>
    </div>

    <AppAlert v-if="error" class="mb-5" type="error" :message="error" />
    <div v-if="loading && !data" class="grid grid-cols-2 gap-3 lg:grid-cols-5" aria-label="Loading dashboard">
      <div v-for="index in 5" :key="index" class="h-32 animate-pulse rounded-lg bg-zinc-100"></div>
    </div>

    <div v-else-if="data" class="space-y-7" aria-live="polite">
      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" class="sr-only">Key performance indicators</h2>
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <RouterLink
            v-for="kpi in kpiCards"
            :key="kpi.key"
            :to="kpi.to"
            class="admin-kpi group rounded-lg border border-zinc-200 bg-white p-4 transition hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-sm"
          >
            <span class="flex items-start justify-between gap-2">
              <span class="text-xs font-medium text-zinc-500">{{ kpi.label }}</span>
              <i :class="['bi text-zinc-400 group-hover:text-zinc-700', kpi.icon]" aria-hidden="true"></i>
            </span>
            <span class="mt-2 block text-3xl font-bold tracking-tight text-black">{{ kpi.value }}</span>
            <span class="mt-1 block text-xs leading-5 text-zinc-500">{{ kpi.context }}</span>
          </RouterLink>
        </div>
      </section>

      <section aria-labelledby="attention-heading">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 id="attention-heading" class="text-lg font-semibold text-black">Requires attention</h2>
            <p class="text-sm text-zinc-500">Items that may block tournament progress</p>
          </div>
          <span class="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600">{{ data.attention.length }} items</span>
        </div>
        <div v-if="data.attention.length" class="admin-attention overflow-hidden rounded-lg border border-zinc-200 bg-white">
          <div v-for="item in data.attention" :key="`${item.kind}-${item.id}`" class="flex flex-col gap-3 border-b border-zinc-100 p-4 last:border-0 sm:flex-row sm:items-center">
            <span :class="['inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border', severityClass(item.severity)]">
              <i :class="['bi', severityIcon(item.severity)]" aria-hidden="true"></i>
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <RouterLink :to="`/tournaments/${item.id}`" class="truncate font-semibold text-black hover:underline">{{ item.name }}</RouterLink>
                <TournamentStatusBadge :state="item.state" />
                <span class="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">{{ attentionLabel(item.kind) }}</span>
              </div>
              <p class="mt-0.5 text-sm text-zinc-600">{{ item.message }}</p>
            </div>
            <RouterLink :to="item.action_to" class="shrink-0 rounded-lg border border-zinc-300 px-3 py-1.5 text-center text-sm font-medium text-zinc-800 hover:bg-zinc-50">
              {{ item.action_label }}
            </RouterLink>
          </div>
        </div>
        <div v-else class="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-8 text-center">
          <i class="bi bi-check-circle text-2xl text-emerald-600" aria-hidden="true"></i>
          <p class="mt-2 font-medium text-zinc-800">Everything is on track</p>
          <p class="text-sm text-zinc-500">There are no tournaments requiring attention.</p>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <section class="lg:col-span-2" aria-labelledby="active-heading">
          <div class="mb-3 flex items-center justify-between">
            <h2 id="active-heading" class="text-lg font-semibold text-black">Active tournaments</h2>
            <RouterLink to="/tournaments?state=active" class="text-sm font-medium text-zinc-600 hover:text-black hover:underline">View all</RouterLink>
          </div>
          <div v-if="data.active_tournaments.length" class="grid gap-3 sm:grid-cols-2">
            <article v-for="tournament in data.active_tournaments" :key="tournament.id" class="admin-tournament-card rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Tournament #{{ tournament.id }}</p>
                  <RouterLink :to="`/tournaments/${tournament.id}`" class="block truncate font-semibold text-black hover:underline">{{ tournament.name }}</RouterLink>
                </div>
                <TournamentStatusBadge :state="tournament.state" />
              </div>
              <p class="mt-4 text-sm font-semibold text-zinc-800">{{ tournament.stage }} <span class="font-normal text-zinc-400">/</span> {{ tournament.round }}</p>
              <div class="mt-3 grid grid-cols-2 divide-x divide-zinc-100 border-y border-zinc-100 py-3 text-sm">
                <div class="pr-3">
                  <p class="text-xs text-zinc-500">Players</p>
                  <p class="mt-0.5 font-semibold text-black"><i class="bi bi-people mr-1 text-zinc-400" aria-hidden="true"></i>{{ tournament.participant_count }}</p>
                </div>
                <div class="pl-3">
                  <p class="text-xs text-zinc-500">Pending matches</p>
                  <p :class="['mt-0.5 font-semibold', tournament.pending_matches ? 'text-amber-700' : 'text-emerald-700']"><i class="bi bi-hourglass-split mr-1" aria-hidden="true"></i>{{ tournament.pending_matches }}</p>
                </div>
              </div>
              <RouterLink :to="`/tournaments/${tournament.id}/progress`" class="mt-4 block rounded-lg bg-zinc-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-black">View progress</RouterLink>
            </article>
          </div>
          <div v-else class="rounded-xl border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500">
            No active tournaments.
            <RouterLink to="/tournaments/new" class="ml-1 font-medium text-zinc-900 hover:underline">Create one</RouterLink>
          </div>
        </section>

        <section aria-labelledby="upcoming-heading">
          <h2 id="upcoming-heading" class="mb-3 text-lg font-semibold text-black">Upcoming</h2>
          <div class="rounded-xl border border-zinc-200 bg-white p-4">
            <ul v-if="data.upcoming_tournaments.length" class="space-y-4">
              <li v-for="tournament in data.upcoming_tournaments" :key="tournament.id" class="border-b border-zinc-100 pb-4 last:border-0 last:pb-0">
                <RouterLink :to="`/tournaments/${tournament.id}`" class="font-medium text-black hover:underline">{{ tournament.name }}</RouterLink>
                <p class="mt-1 text-xs text-zinc-500">{{ formatDate(tournament.starts_at) }}</p>
                <p class="mt-1 text-xs text-zinc-500">{{ tournament.participant_count }}/{{ tournament.min_players }} minimum players</p>
              </li>
            </ul>
            <div v-else class="py-6 text-center text-sm text-zinc-500">Nothing scheduled in this range.</div>
          </div>
        </section>
      </div>

      <section aria-labelledby="users-heading">
        <div class="mb-3 flex items-center justify-between">
          <h2 id="users-heading" class="text-lg font-semibold text-black">Recently added users</h2>
          <RouterLink to="/users" class="text-sm font-medium text-zinc-600 hover:text-black hover:underline">View all</RouterLink>
        </div>
        <div class="overflow-visible rounded-xl border border-zinc-200 bg-white">
          <div v-for="user in data.recent_users" :key="user.id" class="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-4 py-3 last:border-0">
            <div>
              <UserQuickView :user-id="user.id" :username="user.username" />
              <p class="mt-0.5 text-xs text-zinc-500">{{ user.email || 'No email address' }}</p>
            </div>
            <div class="flex items-center gap-2">
              <span :class="['rounded-full px-2 py-0.5 text-xs', user.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700']">{{ user.is_active ? 'Active' : 'Inactive' }}</span>
              <span v-if="user.is_staff" class="rounded-full bg-zinc-900 px-2 py-0.5 text-xs text-white">Staff</span>
            </div>
          </div>
          <div v-if="!data.recent_users.length" class="px-4 py-8 text-center text-sm text-zinc-500">No users yet.</div>
        </div>
      </section>
    </div>
  </div>
</template>
