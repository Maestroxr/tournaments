<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import SelectButton from 'primevue/selectbutton'
import AppAlert from '@/components/AppAlert.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import { useI18n } from '@/i18n'
import type { FinanceSummary } from '@/types/finance'

type RangeDays = 1 | 7 | 30
type Severity = 'critical' | 'warning' | 'info'
type AttentionFilter = 'all' | 'critical' | 'registration' | 'results'
type ActivityKind = 'fixture' | 'wallet' | 'registration'

interface RegistrationSummary {
  registered: number
  unpaid: number
  waitlisted: number
  attention: number
  ready: number
}

interface TournamentSummary {
  id: number
  name: string
  state: string
  starts_at: string | null
  participant_count: number
  min_players: number
  max_players: number | null
  entry_fee?: string
  registration_summary?: RegistrationSummary
}

interface ActiveTournament extends TournamentSummary {
  stage: string
  round: string
  pending_matches: number
  round_completed_matches: number
  round_total_matches: number
  round_progress_percent: number
  next_match: {
    id: number
    player1: string
    player2: string
  } | null
}

interface AttentionItem extends TournamentSummary {
  kind: 'overdue' | 'waiting_players' | 'ready_to_start' | 'pending_matches' | 'draft'
  severity: Severity
  pending_matches?: number
  message: string
  action_label: string
  action_to: string
}

interface KpiValue {
  value: number
  context: string
  attention_count?: number
  days?: number
  missing_players?: number
  delta?: number
}

interface ActivityItem {
  id: string
  kind: ActivityKind
  action: string
  actor: string | null
  subject: string
  amount?: string
  tournament_name: string | null
  created_at: string
  to: string
}

interface DashboardData {
  updated_at: string
  range_days: RangeDays
  kpis: {
    active: KpiValue
    upcoming: KpiValue
    waiting: KpiValue
    pending_matches: KpiValue
  }
  counts: { draft: number; open: number; active: number; finished: number }
  attention: AttentionItem[]
  active_tournaments: ActiveTournament[]
  upcoming_tournaments: TournamentSummary[]
  recent_activity: ActivityItem[]
  finance: FinanceSummary
}

type DashboardPayload = Partial<Omit<DashboardData, 'kpis' | 'counts'>> & {
  kpis?: Partial<DashboardData['kpis']>
  counts?: Partial<DashboardData['counts']>
}

const emptyKpi = (): KpiValue => ({ value: 0, context: '' })
const emptyFinance = (): FinanceSummary => ({
  revenue: '0.00',
  refunds: '0.00',
  prizes: '0.00',
  expenses: '0.00',
  net: '0.00',
  outstanding: '0.00',
  outstanding_count: 0,
})

function normalizeDashboardData(payload: DashboardPayload): DashboardData {
  const activeTournaments = Array.isArray(payload.active_tournaments)
    ? payload.active_tournaments.map(tournament => ({
        ...tournament,
        stage: tournament.stage ?? '',
        round: tournament.round ?? '',
        pending_matches: tournament.pending_matches ?? 0,
        round_completed_matches: tournament.round_completed_matches ?? 0,
        round_total_matches: tournament.round_total_matches ?? tournament.pending_matches ?? 0,
        round_progress_percent: tournament.round_progress_percent ?? 0,
        next_match: tournament.next_match ?? null,
      }))
    : []

  return {
    updated_at: payload.updated_at || new Date().toISOString(),
    range_days: payload.range_days === 1 || payload.range_days === 30 ? payload.range_days : 7,
    kpis: {
      active: { ...emptyKpi(), ...payload.kpis?.active },
      upcoming: { ...emptyKpi(), ...payload.kpis?.upcoming },
      waiting: { ...emptyKpi(), ...payload.kpis?.waiting },
      pending_matches: { ...emptyKpi(), ...payload.kpis?.pending_matches },
    },
    counts: {
      draft: payload.counts?.draft ?? 0,
      open: payload.counts?.open ?? 0,
      active: payload.counts?.active ?? 0,
      finished: payload.counts?.finished ?? 0,
    },
    attention: Array.isArray(payload.attention) ? payload.attention : [],
    active_tournaments: activeTournaments,
    upcoming_tournaments: Array.isArray(payload.upcoming_tournaments)
      ? payload.upcoming_tournaments
      : [],
    recent_activity: Array.isArray(payload.recent_activity) ? payload.recent_activity : [],
    finance: { ...emptyFinance(), ...payload.finance },
  }
}

const data = ref<DashboardData | null>(null)
const { locale, t } = useI18n()
const loading = ref(true)
const error = ref('')
const rangeDays = ref<RangeDays>(7)
const attentionFilter = ref<AttentionFilter>('all')
const ranges = computed<{ value: RangeDays; label: string }[]>(() => [
  { value: 1, label: t('dashboard.ranges.today') },
  { value: 7, label: t('dashboard.ranges.sevenDays') },
  { value: 30, label: t('dashboard.ranges.thirtyDays') },
])

const localeTag = computed(() => (locale.value === 'he' ? 'he-IL' : 'en-US'))

const focusCard = computed(() => {
  const active = data.value?.active_tournaments?.[0]
  if (active) {
    return {
      kind: 'active',
      eyebrow: t('dashboard.primary.activeEyebrow'),
      title: t('dashboard.primary.activeTitle', { name: active.name }),
      description: active.next_match
        ? t('dashboard.nextMatchPlayers', { player1: active.next_match.player1, player2: active.next_match.player2 })
        : countText(
            active.pending_matches,
            'dashboard.primary.pendingOne',
            'dashboard.primary.pendingMany',
          ),
      actionLabel: t('dashboard.primary.openControlRoom'),
      icon: 'bi bi-play-circle',
      to: `/tournaments/${active.id}/live`,
      state: active.state,
      meta: [
        { label: t('dashboard.players'), value: active.participant_count, icon: 'bi-people', direction: 'ltr' as const },
        { label: t('dashboard.pendingMatches'), value: active.pending_matches, icon: 'bi-hourglass-split', direction: 'ltr' as const },
        {
          label: t('dashboard.roundProgress'),
          value: `${active.round_completed_matches}/${active.round_total_matches}`,
          icon: 'bi-bar-chart',
          direction: 'ltr' as const,
        },
      ],
    }
  }

  const upcoming = data.value?.upcoming_tournaments?.[0]
  if (upcoming) {
    const registration = upcoming.registration_summary
    const readyToStart = isReadyToStart(upcoming)
    return {
      kind: 'upcoming',
      eyebrow: t('dashboard.upcoming'),
      title: upcoming.name,
      description: formatDate(upcoming.starts_at),
      actionLabel: t(readyToStart ? 'dashboard.actions.startTournament' : 'dashboard.actions.managePlayers'),
      icon: readyToStart ? 'bi bi-play-circle' : 'bi bi-people',
      to: `/tournaments/${upcoming.id}/${readyToStart ? 'overview' : 'players'}`,
      state: upcoming.state,
      meta: [
        {
          label: t('dashboard.players'),
          value: `${upcoming.participant_count}/${upcoming.min_players}`,
          icon: 'bi-people',
          direction: 'ltr' as const,
        },
        ...(registration ? [
          { label: t('dashboard.unpaid'), value: registration.unpaid, icon: 'bi-credit-card', direction: 'ltr' as const },
        ] : []),
      ],
    }
  }

  const draft = data.value?.attention?.find(item => item.kind === 'draft')
  if (draft) {
    return {
      kind: 'draft',
      eyebrow: t('dashboard.attentionKinds.draft'),
      title: draft.name,
      description: t('dashboard.attentionMessages.draft'),
      actionLabel: t('dashboard.actions.continueEditing'),
      icon: 'bi bi-pencil',
      to: draft.action_to,
      state: draft.state,
      meta: [],
    }
  }

  return {
    kind: 'empty',
    eyebrow: t('tournamentBanner.eyebrow'),
    title: t('tournamentBanner.title'),
    description: t('tournamentBanner.description'),
    actionLabel: t('tournamentBanner.action'),
    icon: 'bi bi-trophy',
    to: '/tournaments/new',
    state: undefined,
    meta: [],
  }
})

function countText(count: number, singularKey: string, pluralKey: string) {
  return t(count === 1 ? singularKey : pluralKey, { count })
}

function isReadyToStart(tournament: TournamentSummary) {
  return tournament.state === 'open' && tournament.participant_count >= tournament.min_players
}

const kpiCards = computed(() => {
  if (!data.value) return []
  return [
    {
      key: 'pending',
      label: t('dashboard.kpi.pending'),
      icon: 'bi-hourglass-split',
      to: '/tournaments?state=active',
      ...data.value.kpis.pending_matches,
      context: t('dashboard.kpiContext.pending'),
      tone: data.value.kpis.pending_matches.value > 0 ? 'critical' : 'neutral',
    },
    {
      key: 'waiting',
      label: t('dashboard.kpi.waiting'),
      icon: 'bi-people',
      to: '/tournaments?view=waiting',
      ...data.value.kpis.waiting,
      context: countText(
        data.value.kpis.waiting.missing_players ?? 0,
        'dashboard.kpiContext.waitingOne',
        'dashboard.kpiContext.waitingMany',
      ),
      tone: (data.value.kpis.waiting.missing_players ?? 0) > 0 ? 'warning' : 'neutral',
    },
    {
      key: 'active',
      label: t('dashboard.kpi.active'),
      icon: 'bi-play-circle',
      to: '/tournaments?state=active',
      ...data.value.kpis.active,
      context: countText(
        data.value.kpis.active.attention_count ?? 0,
        'dashboard.kpiContext.activeOne',
        'dashboard.kpiContext.activeMany',
      ),
      tone: (data.value.kpis.active.attention_count ?? 0) > 0 ? 'warning' : 'neutral',
    },
    {
      key: 'upcoming',
      label: t('dashboard.kpi.upcoming'),
      icon: 'bi-calendar-event',
      to: `/tournaments?view=upcoming&days=${rangeDays.value}`,
      ...data.value.kpis.upcoming,
      context: countText(
        data.value.kpis.upcoming.days ?? rangeDays.value,
        'dashboard.kpiContext.upcomingOne',
        'dashboard.kpiContext.upcomingMany',
      ),
      tone: 'neutral',
    },
  ]
})

const additionalActiveTournaments = computed(() => {
  const active = data.value?.active_tournaments ?? []
  const focusedId = active[0]?.id
  return active.filter(tournament => tournament.id !== focusedId)
})

const visibleUpcomingTournaments = computed(() => {
  const upcoming = data.value?.upcoming_tournaments ?? []
  return data.value?.active_tournaments?.length ? upcoming : upcoming.slice(1)
})

const focusedUpcomingShownAbove = computed(() =>
  !data.value?.active_tournaments?.length && Boolean(data.value?.upcoming_tournaments?.length),
)

const sortedAttention = computed(() => {
  const severityRank: Record<Severity, number> = { critical: 0, warning: 1, info: 2 }
  return [...(data.value?.attention ?? [])].sort((left, right) => {
    const bySeverity = severityRank[left.severity] - severityRank[right.severity]
    if (bySeverity) return bySeverity
    const leftTime = left.starts_at ? Date.parse(left.starts_at) : Number.MAX_SAFE_INTEGER
    const rightTime = right.starts_at ? Date.parse(right.starts_at) : Number.MAX_SAFE_INTEGER
    return leftTime - rightTime || left.id - right.id
  })
})

const filteredAttention = computed(() => sortedAttention.value.filter(item => {
  if (attentionFilter.value === 'critical') return item.severity === 'critical'
  if (attentionFilter.value === 'registration') return ['waiting_players', 'ready_to_start'].includes(item.kind)
  if (attentionFilter.value === 'results') return item.kind === 'pending_matches'
  return true
}))

const attentionFilters = computed<{ value: AttentionFilter; label: string; count: number }[]>(() => [
  { value: 'all', label: t('dashboard.attentionFilters.all'), count: sortedAttention.value.length },
  { value: 'critical', label: t('dashboard.attentionFilters.critical'), count: sortedAttention.value.filter(item => item.severity === 'critical').length },
  { value: 'registration', label: t('dashboard.attentionFilters.registration'), count: sortedAttention.value.filter(item => ['waiting_players', 'ready_to_start'].includes(item.kind)).length },
  { value: 'results', label: t('dashboard.attentionFilters.results'), count: sortedAttention.value.filter(item => item.kind === 'pending_matches').length },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const payload = await apiFetch<DashboardPayload>(`/api/admin/dashboard?days=${rangeDays.value}`)
    data.value = normalizeDashboardData(payload)
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
  if (!value) return t('dashboard.notScheduled')
  return new Date(value).toLocaleString(localeTag.value, { dateStyle: 'medium', timeStyle: 'short' })
}

function formatUpdatedAt(value: string) {
  return new Date(value).toLocaleTimeString(localeTag.value, { hour: '2-digit', minute: '2-digit' })
}

function formatMoney(value?: string) {
  const amount = Number(value ?? 0)
  return new Intl.NumberFormat(localeTag.value, {
    maximumFractionDigits: 2,
  }).format(Math.abs(amount)) + (locale.value === 'he' ? ' קויינס' : ' coins')
}

function registrationPercent(tournament: TournamentSummary) {
  if (tournament.min_players <= 0) return 100
  const registered = tournament.registration_summary?.registered ?? tournament.participant_count
  return Math.min(100, Math.round((registered / tournament.min_players) * 100))
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
  return t(`dashboard.attentionKinds.${kind}`)
}

function attentionMessage(item: AttentionItem) {
  if (item.kind === 'overdue') return t('dashboard.attentionMessages.overdue')
  if (item.kind === 'ready_to_start') {
    return t('dashboard.attentionMessages.readyToStart', { count: item.participant_count })
  }
  if (item.kind === 'waiting_players') {
    const count = Math.max(item.min_players - item.participant_count, 0)
    return countText(
      count,
      'dashboard.attentionMessages.waitingPlayersOne',
      'dashboard.attentionMessages.waitingPlayersMany',
    )
  }
  if (item.kind === 'pending_matches') {
    const count = item.pending_matches ?? 0
    return countText(
      count,
      'dashboard.attentionMessages.pendingMatchesOne',
      'dashboard.attentionMessages.pendingMatchesMany',
    )
  }
  return t('dashboard.attentionMessages.draft')
}

function attentionActionLabel(kind: AttentionItem['kind']) {
  if (kind === 'overdue') return t('dashboard.actions.reviewTournament')
  if (kind === 'ready_to_start') return t('dashboard.actions.startTournament')
  if (kind === 'waiting_players') return t('dashboard.actions.managePlayers')
  if (kind === 'pending_matches') return t('dashboard.primary.openControlRoom')
  return t('dashboard.actions.continueEditing')
}

function attentionUrgency(item: AttentionItem) {
  if (item.kind === 'overdue' && item.starts_at) {
    return t('dashboard.attentionUrgency.overdueSince', { date: formatDate(item.starts_at) })
  }
  if (item.kind === 'waiting_players' && item.starts_at) {
    return t('dashboard.attentionUrgency.startsAt', { date: formatDate(item.starts_at) })
  }
  if (item.kind === 'ready_to_start') return t('dashboard.attentionUrgency.readyNow')
  if (item.kind === 'pending_matches') return t('dashboard.attentionUrgency.resultNow')
  if (item.kind === 'draft') return t('dashboard.attentionUrgency.notPublished')
  return t('dashboard.notScheduled')
}

function activityIcon(kind: ActivityKind) {
  if (kind === 'fixture') return 'bi-trophy'
  if (kind === 'wallet') return 'bi-wallet2'
  return 'bi-person-plus'
}

function activityActionLabel(action: string) {
  const knownActions = new Set([
    'score', 'finish', 'advance', 'disqualify', 'refund', 'player_result',
    'deposit', 'withdrawal', 'tournament_entry', 'tournament_refund',
    'tournament_prize', 'registered',
  ])
  return knownActions.has(action)
    ? t(`dashboard.activityActions.${action}`)
    : t('dashboard.activityActions.updated')
}

function activityDescription(item: ActivityItem) {
  if (item.kind === 'registration') {
    return t('dashboard.activityMessages.registration', { name: item.subject })
  }
  if (item.kind === 'fixture') {
    return t('dashboard.activityMessages.fixture', {
      actor: item.actor || t('dashboard.systemActor'),
      action: activityActionLabel(item.action),
      match: item.subject,
    })
  }
  return t('dashboard.activityMessages.wallet', {
    actor: item.actor || t('dashboard.systemActor'),
    action: activityActionLabel(item.action),
    amount: formatMoney(item.amount),
    name: item.subject,
  })
}

function stateLabel(state: string) {
  return t(`dashboard.states.${state}`)
}

onMounted(load)
</script>

<template>
  <div class="admin-dashboard mx-auto w-full max-w-6xl">
    <header class="admin-page-header mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-black">{{ t('dashboard.title') }}</h1>
        <p class="mt-1 text-sm text-zinc-600">{{ t('dashboard.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-2 text-xs text-zinc-500">
        <span v-if="data">{{ t('dashboard.updatedAt', { time: formatUpdatedAt(data.updated_at) }) }}</span>
        <Button :label="t('common.refresh')" icon="bi bi-arrow-clockwise" size="small" severity="secondary" text :loading="loading" @click="load" />
      </div>
    </header>

    <section class="dashboard-focus-card mb-4" :aria-label="focusCard.title">
      <div class="min-w-0">
        <p class="dashboard-focus-card__eyebrow">{{ focusCard.eyebrow }}</p>
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="dashboard-focus-card__title" dir="auto">{{ focusCard.title }}</h2>
          <TournamentStatusBadge
            v-if="focusCard.state"
            :state="focusCard.state"
            :label="stateLabel(focusCard.state)"
          />
        </div>
        <p class="dashboard-focus-card__description" dir="auto">{{ focusCard.description }}</p>
        <dl v-if="focusCard.meta.length" class="dashboard-focus-card__meta">
          <div v-for="item in focusCard.meta" :key="item.label">
            <dt><i :class="['bi', item.icon]" aria-hidden="true"></i>{{ item.label }}</dt>
            <dd :dir="item.direction">{{ item.value }}</dd>
          </div>
        </dl>
      </div>
      <Button
        as="router-link"
        :to="focusCard.to"
        :label="focusCard.actionLabel"
        :icon="focusCard.icon"
        rounded
        class="dashboard-focus-card__action"
      />
    </section>

    <AppAlert v-if="error" class="mb-5" type="error" :message="error" />
    <div v-if="loading && !data" class="grid grid-cols-2 gap-3 lg:grid-cols-5" :aria-label="t('dashboard.loadingAria')">
      <div v-for="index in 5" :key="index" class="h-32 animate-pulse rounded-lg bg-zinc-100"></div>
    </div>

    <div v-else-if="data" class="space-y-7" aria-live="polite">
      <section aria-labelledby="attention-heading">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 id="attention-heading" class="text-lg font-semibold text-black">{{ t('dashboard.attention') }}</h2>
            <p class="text-sm text-zinc-500">{{ t('dashboard.attentionSubtitle') }}</p>
          </div>
          <span class="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600">{{ countText(filteredAttention.length, 'dashboard.itemOne', 'dashboard.items') }}</span>
        </div>
        <div v-if="data.attention.length" class="dashboard-attention-filters mb-3 flex flex-wrap gap-2" role="group" :aria-label="t('dashboard.attentionFilterAria')">
          <button
            v-for="filter in attentionFilters"
            :key="filter.value"
            type="button"
            :aria-pressed="attentionFilter === filter.value"
            :class="[
              'rounded-full border px-3 py-1.5 text-sm font-medium transition',
              attentionFilter === filter.value
                ? 'border-zinc-900 bg-zinc-900 text-white'
                : 'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-400 hover:text-black',
            ]"
            @click="attentionFilter = filter.value"
          >
            {{ filter.label }} <span class="ms-1 opacity-70" dir="ltr">{{ filter.count }}</span>
          </button>
        </div>
        <div v-if="filteredAttention.length" class="admin-attention overflow-hidden rounded-lg border border-zinc-200 bg-white">
          <div v-for="item in filteredAttention" :key="`${item.kind}-${item.id}`" class="flex flex-col gap-3 border-b border-zinc-100 p-4 last:border-0 sm:flex-row sm:items-center">
            <span :class="['inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border', severityClass(item.severity)]">
              <i :class="['bi', severityIcon(item.severity)]" aria-hidden="true"></i>
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <RouterLink :to="`/tournaments/${item.id}`" class="truncate font-semibold text-black hover:underline" dir="auto">{{ item.name }}</RouterLink>
                <TournamentStatusBadge :state="item.state" :label="stateLabel(item.state)" />
                <span class="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">{{ attentionLabel(item.kind) }}</span>
              </div>
              <p class="mt-0.5 text-sm text-zinc-600">{{ attentionMessage(item) }}</p>
              <p class="mt-1 flex items-center gap-1.5 text-xs font-medium text-zinc-500" dir="auto">
                <i class="bi bi-clock" aria-hidden="true"></i>{{ attentionUrgency(item) }}
              </p>
            </div>
            <RouterLink :to="item.action_to" class="shrink-0 rounded-lg border border-zinc-300 px-3 py-1.5 text-center text-sm font-medium text-zinc-800 hover:bg-zinc-50">
              {{ attentionActionLabel(item.kind) }}
            </RouterLink>
          </div>
        </div>
        <div v-else-if="data.attention.length" class="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-6 text-center">
          <i class="bi bi-funnel text-xl text-zinc-400" aria-hidden="true"></i>
          <p class="mt-2 text-sm font-medium text-zinc-700">{{ t('dashboard.noAttentionInFilter') }}</p>
        </div>
        <div v-else class="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-8 text-center">
          <i class="bi bi-check-circle text-2xl text-emerald-600" aria-hidden="true"></i>
          <p class="mt-2 font-medium text-zinc-800">{{ t('dashboard.allOnTrack') }}</p>
          <p class="text-sm text-zinc-500">{{ t('dashboard.noAttention') }}</p>
        </div>
      </section>

      <section aria-labelledby="upcoming-heading">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="upcoming-heading" class="text-lg font-semibold text-black">{{ t('dashboard.todayAndUpcoming') }}</h2>
          <SelectButton :model-value="rangeDays" :options="ranges" option-label="label" option-value="value" :aria-label="t('dashboard.rangeAria')" @update:model-value="selectRange($event as RangeDays)" />
        </div>
        <ul v-if="visibleUpcomingTournaments.length" class="dashboard-upcoming-grid grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <li v-for="tournament in visibleUpcomingTournaments" :key="tournament.id" class="rounded-lg border border-zinc-200 bg-white p-4">
            <RouterLink :to="`/tournaments/${tournament.id}`" class="font-medium text-black hover:underline" dir="auto">{{ tournament.name }}</RouterLink>
            <p class="mt-1 text-sm text-zinc-500" dir="auto"><i class="bi bi-calendar-event me-1" aria-hidden="true"></i>{{ formatDate(tournament.starts_at) }}</p>
            <div class="mt-3">
              <div class="mb-1.5 flex items-center justify-between gap-3 text-xs text-zinc-500">
                <span>{{ t('dashboard.registrationReadiness') }}</span>
                <strong class="font-semibold text-zinc-700" dir="ltr">{{ tournament.registration_summary?.registered ?? tournament.participant_count }}/{{ tournament.min_players }}</strong>
              </div>
              <div
                class="h-2 overflow-hidden rounded-full bg-zinc-100"
                role="progressbar"
                :aria-label="t('dashboard.registrationProgressAria', { name: tournament.name })"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="registrationPercent(tournament)"
              >
                <span class="block h-full rounded-full bg-blue-600 transition-all" :style="{ width: `${registrationPercent(tournament)}%` }"></span>
              </div>
            </div>
            <div v-if="tournament.registration_summary" class="mt-3 flex flex-wrap gap-2 text-xs">
              <span :class="['rounded-full px-2 py-1 font-medium', tournament.registration_summary.unpaid ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-700']">
                <i :class="['bi me-1', tournament.registration_summary.unpaid ? 'bi-credit-card' : 'bi-check-circle']" aria-hidden="true"></i>
                {{ tournament.registration_summary.unpaid ? t('dashboard.unpaidCount', { count: tournament.registration_summary.unpaid }) : t('dashboard.paymentsSettled') }}
              </span>
              <span v-if="tournament.registration_summary.waitlisted" class="rounded-full bg-blue-50 px-2 py-1 font-medium text-blue-700">
                {{ t('dashboard.waitlistedCount', { count: tournament.registration_summary.waitlisted }) }}
              </span>
            </div>
            <RouterLink :to="`/tournaments/${tournament.id}/${isReadyToStart(tournament) ? 'overview' : 'players'}`" class="mt-4 block rounded-lg border border-zinc-300 px-3 py-2 text-center text-sm font-medium text-zinc-800 hover:bg-zinc-50">
              {{ t(isReadyToStart(tournament) ? 'dashboard.actions.startTournament' : 'dashboard.actions.managePlayers') }}
            </RouterLink>
          </li>
        </ul>
        <div v-else class="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-6 text-center text-sm text-zinc-500">
          {{ t(focusedUpcomingShownAbove ? 'dashboard.focusedUpcomingShownAbove' : 'dashboard.nothingScheduled') }}
        </div>
      </section>

      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" class="sr-only">{{ t('dashboard.kpis') }}</h2>
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <RouterLink
            v-for="kpi in kpiCards"
            :key="kpi.key"
            :to="kpi.to"
            :class="[
              'admin-kpi group rounded-lg border border-zinc-200 bg-white p-4 transition hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-sm',
              `admin-kpi--${kpi.tone}`,
            ]"
          >
            <span class="flex items-start justify-between gap-2">
              <span class="text-xs font-medium text-zinc-500">{{ kpi.label }}</span>
              <i :class="['bi text-zinc-400 group-hover:text-zinc-700', kpi.icon]" aria-hidden="true"></i>
            </span>
            <span class="mt-2 block text-3xl font-bold tracking-tight text-black" dir="ltr">{{ kpi.value }}</span>
            <span class="mt-1 block text-xs leading-5 text-zinc-500">{{ kpi.context }}</span>
          </RouterLink>
        </div>
      </section>

      <section aria-labelledby="finance-preview-heading">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 id="finance-preview-heading" class="text-lg font-semibold text-black">{{ t('dashboard.finance.title') }}</h2>
            <p class="text-sm text-zinc-500">{{ t('dashboard.finance.subtitle') }}</p>
          </div>
          <RouterLink to="/transfers/finance" class="text-sm font-medium text-zinc-600 hover:text-black hover:underline">{{ t('dashboard.finance.open') }}</RouterLink>
        </div>
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div class="rounded-lg border border-zinc-200 bg-white p-4">
            <span class="text-xs font-medium text-zinc-500">{{ t('finance.revenue') }}</span>
            <strong class="mt-2 block text-xl font-bold text-emerald-700" dir="ltr">{{ formatMoney(data.finance.revenue) }}</strong>
          </div>
          <div class="rounded-lg border border-zinc-200 bg-white p-4">
            <span class="text-xs font-medium text-zinc-500">{{ t('finance.expenses') }}</span>
            <strong class="mt-2 block text-xl font-bold text-red-700" dir="ltr">{{ formatMoney(data.finance.expenses) }}</strong>
          </div>
          <div class="rounded-lg border border-zinc-200 bg-white p-4">
            <span class="text-xs font-medium text-zinc-500">{{ t('finance.net') }}</span>
            <strong :class="['mt-2 block text-xl font-bold', Number(data.finance.net) >= 0 ? 'text-emerald-700' : 'text-red-700']" dir="ltr">{{ formatMoney(data.finance.net) }}</strong>
          </div>
          <div class="rounded-lg border border-zinc-200 bg-white p-4">
            <span class="text-xs font-medium text-zinc-500">{{ t('finance.outstanding') }}</span>
            <strong class="mt-2 block text-xl font-bold text-amber-700" dir="ltr">{{ formatMoney(data.finance.outstanding) }}</strong>
          </div>
        </div>
      </section>

      <section v-if="additionalActiveTournaments.length" aria-labelledby="active-heading">
        <div class="mb-3 flex items-center justify-between">
          <h2 id="active-heading" class="text-lg font-semibold text-black">{{ t('dashboard.additionalActiveTournaments') }}</h2>
          <RouterLink to="/tournaments?state=active" class="text-sm font-medium text-zinc-600 hover:text-black hover:underline">{{ t('dashboard.viewAll') }}</RouterLink>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <article v-for="tournament in additionalActiveTournaments" :key="tournament.id" class="admin-tournament-card rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{{ t('dashboard.tournamentNumber', { id: tournament.id }) }}</p>
                <RouterLink :to="`/tournaments/${tournament.id}`" class="block truncate font-semibold text-black hover:underline" dir="auto">{{ tournament.name }}</RouterLink>
              </div>
              <TournamentStatusBadge :state="tournament.state" :label="stateLabel(tournament.state)" />
            </div>
            <p class="mt-4 text-sm font-semibold text-zinc-800" dir="auto">{{ tournament.stage }} <span class="font-normal text-zinc-400">/</span> {{ tournament.round }}</p>
            <div class="mt-3">
              <div class="mb-1.5 flex items-center justify-between gap-3 text-xs text-zinc-500">
                <span>{{ t('dashboard.roundProgress') }}</span>
                <strong class="font-semibold text-zinc-700" dir="ltr">{{ tournament.round_completed_matches }}/{{ tournament.round_total_matches }}</strong>
              </div>
              <div
                class="h-2 overflow-hidden rounded-full bg-zinc-100"
                role="progressbar"
                :aria-label="t('dashboard.roundProgressAria', { name: tournament.name })"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="tournament.round_progress_percent"
              >
                <span class="block h-full rounded-full bg-blue-600 transition-all" :style="{ width: `${tournament.round_progress_percent}%` }"></span>
              </div>
            </div>
            <p class="mt-3 min-h-5 text-sm text-zinc-600" dir="auto">
              <i class="bi bi-controller me-1.5 text-zinc-400" aria-hidden="true"></i>
              <span v-if="tournament.next_match">{{ t('dashboard.nextMatchPlayers', { player1: tournament.next_match.player1, player2: tournament.next_match.player2 }) }}</span>
              <span v-else>{{ t('dashboard.noNextMatch') }}</span>
            </p>
            <div class="mt-3 grid grid-cols-2 divide-x divide-zinc-100 border-y border-zinc-100 py-3 text-sm">
              <div class="pe-3">
                <p class="text-xs text-zinc-500">{{ t('dashboard.players') }}</p>
                <p class="mt-0.5 font-semibold text-black" dir="ltr"><i class="bi bi-people me-1 text-zinc-400" aria-hidden="true"></i>{{ tournament.participant_count }}</p>
              </div>
              <div class="ps-3">
                <p class="text-xs text-zinc-500">{{ t('dashboard.pendingMatches') }}</p>
                <p :class="['mt-0.5 font-semibold', tournament.pending_matches ? 'text-amber-700' : 'text-emerald-700']" dir="ltr"><i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>{{ tournament.pending_matches }}</p>
              </div>
            </div>
            <RouterLink :to="`/tournaments/${tournament.id}/live`" class="mt-4 block rounded-lg bg-zinc-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-black">{{ t('dashboard.primary.openControlRoom') }}</RouterLink>
          </article>
        </div>
      </section>

      <section aria-labelledby="activity-heading">
        <div class="mb-3">
          <h2 id="activity-heading" class="text-lg font-semibold text-black">{{ t('dashboard.recentActivity') }}</h2>
          <p class="text-sm text-zinc-500">{{ t('dashboard.recentActivitySubtitle') }}</p>
        </div>
        <div v-if="data.recent_activity.length" class="overflow-hidden rounded-lg border border-zinc-200 bg-white">
          <RouterLink
            v-for="item in data.recent_activity"
            :key="item.id"
            :to="item.to"
            class="group flex items-start gap-3 border-b border-zinc-100 px-4 py-3 transition last:border-0 hover:bg-zinc-50"
          >
            <span class="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-600 group-hover:bg-zinc-200">
              <i :class="['bi', activityIcon(item.kind)]" aria-hidden="true"></i>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium text-zinc-800" dir="auto">{{ activityDescription(item) }}</span>
              <span v-if="item.tournament_name" class="mt-0.5 block truncate text-xs text-zinc-500" dir="auto">{{ item.tournament_name }}</span>
            </span>
            <time :datetime="item.created_at" class="shrink-0 text-xs text-zinc-500" dir="auto">{{ formatDate(item.created_at) }}</time>
          </RouterLink>
        </div>
        <div v-else class="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-6 text-center text-sm text-zinc-500">
          {{ t('dashboard.noRecentActivity') }}
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard-focus-card {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  overflow: hidden;
  padding: 14px 18px;
  border: 1px solid #2879ef;
  border-radius: 12px;
  background: linear-gradient(115deg, #075cf2 0%, #075dcc 65%, #0854aa 100%);
  color: #fff;
}
.dashboard-focus-card::after {
  position: absolute;
  z-index: -1;
  inset-inline-end: -34px;
  top: -64px;
  width: 190px;
  height: 190px;
  border-radius: 50%;
  background: rgb(255 255 255 / 8%);
  content: '';
}
.dashboard-focus-card__eyebrow {
  margin: 0 0 4px;
  color: #dbeafe;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.dashboard-focus-card__title {
  margin: 0;
  color: #fff;
  font-size: 19px;
  font-weight: 750;
  line-height: 1.35;
}
.dashboard-focus-card :deep(.p-badge),
.dashboard-focus-card :deep(span[class*='rounded-full']) {
  border-color: rgb(255 255 255 / 38%);
  background: rgb(6 34 88 / 32%);
  color: #fff;
}
.dashboard-focus-card__description {
  margin: 3px 0 0;
  color: #e6efff;
  font-size: 12px;
}
.dashboard-focus-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  margin: 7px 0 0;
}
.dashboard-focus-card__meta dt {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #bfdbfe;
  font-size: 10px;
}
.dashboard-focus-card__meta dd {
  margin: 1px 0 0;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.dashboard-focus-card .dashboard-focus-card__action {
  flex-shrink: 0;
  min-height: 40px;
  padding: 8px 18px;
  border: 1px solid #fff;
  background: #fff;
  color: #075bbb;
  font-size: 13px;
  font-weight: 700;
  box-shadow: none;
}
.admin-kpi--critical {
  border-color: rgb(248 113 113 / 52%) !important;
  box-shadow: inset 0 3px 0 #ef4444;
}
.admin-kpi--warning {
  border-color: rgb(245 158 11 / 46%) !important;
  box-shadow: inset 0 3px 0 #f59e0b;
}
@media (max-width: 540px) {
  .dashboard-focus-card {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
  }
  .dashboard-focus-card__action { align-self: flex-start; }
}
</style>
