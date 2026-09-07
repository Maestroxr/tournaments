<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import AppAlert from '@/components/AppAlert.vue'
import TournamentMetaItem from '@/components/TournamentMetaItem.vue'
import TournamentActions from '@/components/tournament/TournamentActions.vue'
import TournamentAttentionPanel, {
  type TournamentAttentionItem,
} from '@/components/tournament/TournamentAttentionPanel.vue'
import TournamentOverviewMetrics, {
  type TournamentOverviewMetric,
} from '@/components/tournament/TournamentOverviewMetrics.vue'
import TournamentStructureCard from '@/components/tournament/TournamentStructureCard.vue'
import TournamentDangerDialog from '@/components/tournament/TournamentDangerDialog.vue'
import StartTournamentDialog from '@/components/tournament/StartTournamentDialog.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import { useTournamentWorkspace } from '@/composables/useTournamentWorkspace'
import { useI18n } from '@/i18n'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'
import * as yaml from 'js-yaml'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const workspace = useTournamentWorkspace()
const { t: translate, locale } = useI18n()
const starting = ref(false)
const publishing = ref(false)
const showStartDialog = ref(false)
const startError = ref('')
const showRevertDialog = ref(false)
const reverting = ref(false)
const revertError = ref('')
const showDeleteDialog = ref(false)
const deleting = ref(false)
const deleteError = ref('')
const loading = ref(true)
const error = ref('')
const loadFailed = ref(false)
interface TournamentParticipant {
  id: number
  name: string
  user_id: number | null
  username: string | null
}

interface TournamentDetail {
  id: number
  name: string
  state: string
  lifecycle_state: string
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
  definition: string
  participants: TournamentParticipant[]
  published: boolean
  registration_summary?: {
    registered: number
    unpaid: number
    waitlisted: number
    attention: number
    ready: number
  }
}
const t = ref<TournamentDetail | null>(null)
const overviewProgress = ref<TournamentProgressData | null>(null)
const overviewProgressFailed = ref(false)
const editing = ref(false)
const editYaml = ref('')
const editName = ref('')
const editStartsDate = ref('')
const editStartsTime = ref('')
const editMin = ref(6)
const editMax = ref<number | ''>('')
const editPoints = ref(5)
const editTime = ref('normal')
const editDoubling = ref(true)
const editEntryFee = ref(0)
const editPrizeMoney = ref(0)
const savedRawDefinition = ref('')
const savedDraftFingerprint = ref('')
const pad = (value: number) => String(value).padStart(2, '0')
const dateInputValue = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const timeInputValue = (date: Date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`
const now = new Date()
const minStartsDate = ref(dateInputValue(now))
const minStartsTime = computed(() => editStartsDate.value === minStartsDate.value ? timeInputValue(new Date()) : undefined)

interface Stage { id: string; name: string; mode: string }
const stageModeOptions = computed(() => [
  { value: 'knockout', label: translate('tournamentSettings.stageModes.knockout') },
  { value: 'division', label: translate('tournamentSettings.stageModes.division') },
  { value: 'groups', label: translate('tournamentSettings.stageModes.groups') },
])
const stages = ref<Stage[]>([])
const podium = ref<string[]>([])
const isSettingsRoute = computed(() => route.name === 'tournament-settings')
const isOverviewRoute = computed(() => route.name === 'tournament-detail')

const readinessItems = computed(() => {
  if (!t.value) return []
  const hasFormat = stages.value.length > 0 && podium.value.length > 0
  const enoughPlayers = t.value.participant_count >= t.value.min_players
  return [
    { id: 'details', done: Boolean(t.value.name && t.value.target_points >= 1) },
    { id: 'format', done: hasFormat },
    { id: 'schedule', done: Boolean(t.value.starts_at) },
    { id: 'published', done: t.value.state !== 'draft' || t.value.published },
    { id: 'players', done: ['active', 'finished'].includes(t.value.state) || enoughPlayers },
  ]
})
const hasFormat = computed(() => stages.value.length > 0 && podium.value.length > 0)
const readinessComplete = computed(() => readinessItems.value.filter(item => item.done).length)
const allFixtures = computed<TournamentFixture[]>(() => Object.values(overviewProgress.value?.stages ?? {})
  .flatMap(stage => stage.levels.flatMap(level => level.fixtures)))
const pendingFixtures = computed(() => allFixtures.value.filter(fixture =>
  !fixture.is_confirmed && fixture.player1 && fixture.player2))
const awaitingConfirmation = computed(() => pendingFixtures.value.filter(fixture => fixture.confirmations > 0))
const confirmedFixtures = computed(() => allFixtures.value.filter(fixture => fixture.is_confirmed))

const overviewMetrics = computed<TournamentOverviewMetric[]>(() => {
  if (!t.value) return []
  const capacity = t.value.max_players
  const enoughPlayers = t.value.participant_count >= t.value.min_players
  const scheduleSet = Boolean(t.value.starts_at)
  const metrics: TournamentOverviewMetric[] = [
    {
      id: 'registration',
      label: translate('tournamentOverview.registration'),
      value: capacity === null ? `${t.value.participant_count}` : `${t.value.participant_count}/${capacity}`,
      hint: translate(enoughPlayers ? 'tournamentOverview.minimumMet' : 'tournamentOverview.minimumNeeded', {
        count: Math.max(0, t.value.min_players - t.value.participant_count),
        minimum: t.value.min_players,
      }),
      icon: 'bi-people',
      tone: enoughPlayers ? 'good' : 'warning',
    },
    {
      id: 'readiness',
      label: translate('tournamentOverview.readiness'),
      value: `${readinessComplete.value}/${readinessItems.value.length}`,
      hint: translate('tournamentOverview.checksComplete'),
      icon: 'bi-check2-square',
      tone: readinessComplete.value === readinessItems.value.length ? 'good' : 'warning',
    },
    {
      id: 'schedule',
      label: translate('tournamentOverview.schedule'),
      value: relativeStart(t.value.starts_at),
      hint: scheduleSet ? formatDate(t.value.starts_at) : translate('tournamentOverview.addScheduleHint'),
      icon: 'bi-calendar-event',
      tone: scheduleSet ? 'neutral' : 'warning',
    },
    {
      id: 'finance',
      label: translate('tournamentOverview.entryAndPrize'),
      value: Number(t.value.entry_fee || 0) > 0
        ? Number(t.value.entry_fee).toFixed(2)
        : translate('tournamentOverview.freeEntry'),
      hint: translate('tournamentOverview.prizeValue', { amount: Number(t.value.prize_money || 0).toFixed(2) }),
      icon: 'bi-wallet2',
    },
  ]
  if (['active', 'finished'].includes(t.value.state)) metrics.push({
    id: 'matches',
    label: translate('tournamentOverview.matchResults'),
    value: overviewProgressFailed.value ? '—' : `${confirmedFixtures.value.length}/${allFixtures.value.length}`,
    hint: overviewProgressFailed.value
      ? translate('tournamentOverview.matchDataUnavailable')
      : translate('tournamentOverview.confirmedMatches'),
    icon: 'bi-controller',
    tone: pendingFixtures.value.length === 0 && allFixtures.value.length > 0 ? 'good' : 'neutral',
  })
  return metrics
})

const attentionItems = computed<TournamentAttentionItem[]>(() => {
  if (!t.value) return []
  const root = `/tournaments/${t.value.id}`
  const items: TournamentAttentionItem[] = []
  if (!hasFormat.value) items.push({
    id: 'format',
    title: translate('tournamentOverview.formatMissing'),
    detail: translate('tournamentOverview.formatMissingHint'),
    action: translate('tournamentOverview.reviewSettings'),
    to: `${root}/settings`,
    severity: 'critical',
  })
  if (!t.value.starts_at && !['active', 'finished'].includes(t.value.state)) items.push({
    id: 'schedule',
    title: translate('tournamentOverview.scheduleMissing'),
    detail: translate('tournamentOverview.scheduleMissingHint'),
    action: translate('tournamentOverview.reviewSettings'),
    to: `${root}/settings`,
    severity: 'warning',
  })
  if (t.value.state === 'open' && t.value.participant_count < t.value.min_players) {
    const count = t.value.min_players - t.value.participant_count
    items.push({
      id: 'players',
      title: translate('tournamentOverview.playersMissing', { count }),
      detail: translate('tournamentOverview.playersMissingHint', { minimum: t.value.min_players }),
      action: translate('tournamentOverview.managePlayers'),
      to: `${root}/players`,
      severity: 'critical',
    })
  }
  const unpaid = t.value.registration_summary?.unpaid ?? 0
  const waitlisted = t.value.registration_summary?.waitlisted ?? 0
  const participantAttention = unpaid + waitlisted
  if (t.value.state === 'open' && participantAttention > 0) {
    const detail = [
      unpaid > 0 ? translate('dashboard.unpaidCount', { count: unpaid }) : '',
      waitlisted > 0 ? translate('dashboard.waitlistedCount', { count: waitlisted }) : '',
    ].filter(Boolean).join(' · ')
    items.push({
      id: 'participant-readiness',
      title: translate('tournamentOverview.participantsNeedAttention', {
        count: participantAttention,
      }),
      detail,
      action: translate('tournamentOverview.managePlayers'),
      to: `${root}/players`,
      severity: 'warning',
    })
  }
  if (t.value.state === 'open' && t.value.starts_at && new Date(t.value.starts_at).getTime() < Date.now()) items.push({
    id: 'overdue',
    title: translate('tournamentOverview.startOverdue'),
    detail: translate('tournamentOverview.startOverdueHint'),
    action: translate('tournamentOverview.reviewSettings'),
    to: `${root}/settings`,
    severity: 'critical',
  })
  if (t.value.state === 'active' && awaitingConfirmation.value.length > 0) items.push({
    id: 'confirmation',
    title: translate('tournamentOverview.awaitingConfirmation', { count: awaitingConfirmation.value.length }),
    detail: translate('tournamentOverview.awaitingConfirmationHint'),
    action: translate('tournamentOverview.openMatches'),
    to: `${root}/bracket`,
    severity: 'critical',
  })
  const waitingForResults = pendingFixtures.value.length - awaitingConfirmation.value.length
  if (t.value.state === 'active' && waitingForResults > 0) items.push({
    id: 'pending-matches',
    title: translate('tournamentOverview.matchesPending', { count: waitingForResults }),
    detail: translate('tournamentOverview.matchesPendingHint'),
    action: translate('tournamentOverview.openLive'),
    to: `${root}/live`,
    severity: 'info',
  })
  if (['active', 'finished'].includes(t.value.state) && overviewProgressFailed.value) items.push({
    id: 'progress-unavailable',
    title: translate('tournamentOverview.progressUnavailable'),
    detail: translate('tournamentOverview.progressUnavailableHint'),
    action: translate('tournamentOverview.tryMatches'),
    to: `${root}/bracket`,
    severity: 'warning',
  })
  return items
})

function parseDefinition(def: string) {
  try {
    const obj = yaml.load(def) as unknown as { stages?: Stage[]; podium?: string[] }
    stages.value = (obj?.stages || []).map((s) => ({ id: s.id, name: s.name || s.id, mode: s.mode }))
    podium.value = obj?.podium || []
    editYaml.value = def
  } catch { stages.value = []; podium.value = [] }
}
function parseTournamentMeta() {
  if (!t.value) return
  editName.value = t.value.name || ''
  if (t.value.starts_at) {
    const d = new Date(t.value.starts_at)
    if (!isNaN(d.getTime())) {
      editStartsDate.value = dateInputValue(d)
      editStartsTime.value = timeInputValue(d)
    }
  } else { editStartsDate.value = minStartsDate.value; editStartsTime.value = timeInputValue(now) }
  editMin.value = t.value.min_players ?? 6
  editMax.value = t.value.max_players ?? ''
  editPoints.value = t.value.target_points ?? 5
  editTime.value = t.value.time_control ?? 'normal'
  editDoubling.value = t.value.doubling_enabled ?? true
  editEntryFee.value = Number(t.value.entry_fee ?? 0)
  editPrizeMoney.value = Number(t.value.prize_money ?? 0)
}

async function load() {
  loading.value = true
  error.value = ''
  loadFailed.value = false
  overviewProgress.value = null
  overviewProgressFailed.value = false
  try {
    const tid = props.id || String(route.params.id)
    t.value = await apiFetch<TournamentDetail>(`/api/admin/tournaments/${tid}`)
    if (t.value?.definition) parseDefinition(t.value.definition)
    parseTournamentMeta()
    savedRawDefinition.value = editYaml.value
    savedDraftFingerprint.value = draftFingerprint()
    editing.value =
      t.value?.state === 'draft' && (route.query.edit === '1' || isSettingsRoute.value)
    if (isOverviewRoute.value && ['active', 'finished'].includes(t.value.state)) {
      await loadOverviewProgress(tid)
    }
  } catch (e: unknown) {
    error.value = formatApiError(e)
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(
  () => route.name,
  () => {
    editing.value = t.value?.state === 'draft' && isSettingsRoute.value
    if (isOverviewRoute.value && t.value && ['active', 'finished'].includes(t.value.state) && !overviewProgress.value) {
      void loadOverviewProgress(String(t.value.id))
    }
  },
)

async function loadOverviewProgress(tid: string) {
  overviewProgressFailed.value = false
  try {
    overviewProgress.value = await apiFetch<TournamentProgressData>(`/api/admin/tournaments/${tid}/progress`)
  } catch {
    overviewProgress.value = null
    overviewProgressFailed.value = true
  }
}

function requestDelete() {
  if (deleting.value || t.value?.state !== 'draft') return
  deleteError.value = ''
  showDeleteDialog.value = true
}

async function deleteDraft() {
  if (!showDeleteDialog.value || deleting.value || t.value?.state !== 'draft') return
  deleting.value = true
  deleteError.value = ''
  try {
    const tid = props.id || String(route.params.id)
    await apiFetch(`/api/admin/tournaments/${tid}`, { method: 'DELETE' })
    showDeleteDialog.value = false
    router.push('/tournaments')
  } catch (e: unknown) {
    deleteError.value = formatApiError(e)
  } finally {
    deleting.value = false
  }
}

function addStage() { stages.value.push({ id: `stage_${stages.value.length + 1}`, name: translate('tournamentSettings.newStage'), mode: 'knockout' }) }
function removeStage(idx: number) { stages.value.splice(idx, 1) }
function addPodium() { const ref = stages.value[0]?.id || 'main_round'; podium.value.push(`${ref}.placements[0]`) }

function draftPayload() {
  const parsedDefinition = yaml.load(editYaml.value) as unknown
  const rawDefinitionChanged = editYaml.value !== savedRawDefinition.value
  const rawDefinition = parsedDefinition && typeof parsedDefinition === 'object' && !Array.isArray(parsedDefinition)
    ? parsedDefinition as Record<string, unknown>
    : null
  const rawStages = Array.isArray(rawDefinition?.stages)
    ? rawDefinition.stages.filter(stage => stage && typeof stage === 'object' && !Array.isArray(stage)) as Record<string, unknown>[]
    : []
  const definition = stages.value.length && rawDefinition && !rawDefinitionChanged
    ? {
        ...rawDefinition,
        stages: stages.value.map((stage, index) => ({
          ...(rawStages.find(rawStage => rawStage.id === stage.id) ?? rawStages[index] ?? {}),
          id: stage.id,
          name: stage.name,
          mode: stage.mode,
        })),
        podium: [...podium.value],
      }
    : parsedDefinition
  const startsAt = editStartsDate.value
    ? `${editStartsDate.value}T${editStartsTime.value || '00:00'}`
    : null
  return {
    name: editName.value,
    definition,
    starts_at: startsAt,
    min_players: Number(editMin.value),
    max_players: editMax.value === '' ? null : Number(editMax.value),
    target_points: Number(editPoints.value),
    time_control: editTime.value,
    doubling_enabled: editDoubling.value,
    entry_fee: Number(editEntryFee.value),
    prize_money: Number(editPrizeMoney.value),
  }
}

function draftFingerprint() {
  return JSON.stringify(draftPayload())
}

const draftChanged = computed(() => {
  if (t.value?.state !== 'draft') return false
  try {
    return draftFingerprint() !== savedDraftFingerprint.value
  } catch {
    return true
  }
})

async function publishAndManagePlayers() {
  if (publishing.value || t.value?.state !== 'draft' || !hasFormat.value) return
  publishing.value = true
  error.value = ''
  try {
    const tid = props.id || String(route.params.id)
    if (draftChanged.value) {
      const payload = draftPayload()
      await apiFetch(`/api/admin/tournaments/${tid}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      savedRawDefinition.value = editYaml.value
      savedDraftFingerprint.value = JSON.stringify(payload)
    }
    await apiFetch(`/api/admin/tournaments/${tid}/publish`, { method: 'POST' })
    await load()
    await workspace?.refresh()
    const publishedTournament = t.value as TournamentDetail | null
    if (publishedTournament?.state === 'open') {
      router.push(`/tournaments/${publishedTournament.id}/players`)
    }
  } catch (e: unknown) {
    error.value = formatApiError(e)
  } finally {
    publishing.value = false
  }
}
function requestRevertToDraft() {
  if (reverting.value || t.value?.state !== 'open') return
  revertError.value = ''
  showRevertDialog.value = true
}
async function revertToDraft() {
  if (!showRevertDialog.value || reverting.value || t.value?.state !== 'open') return
  reverting.value = true
  revertError.value = ''
  try {
    const tid = props.id || String(route.params.id)
    await apiFetch(`/api/admin/tournaments/${tid}/draft`, { method: 'POST' })
    showRevertDialog.value = false
    await load()
    await workspace?.refresh()
  } catch (e: unknown) {
    revertError.value = formatApiError(e)
  } finally {
    reverting.value = false
  }
}
function requestStart() {
  if (starting.value || t.value?.state !== 'open' || t.value.participant_count < t.value.min_players) return
  startError.value = ''
  showStartDialog.value = true
}
async function start() {
  if (!showStartDialog.value || starting.value || t.value?.state !== 'open' || t.value.participant_count < t.value.min_players) return
  starting.value = true
  startError.value = ''
  try {
    const tid = props.id || String(route.params.id)
    await apiFetch(`/api/admin/tournaments/${tid}/start`, { method: 'POST' })
    showStartDialog.value = false
    await load()
    await workspace?.refresh()
  } catch (e: unknown) { startError.value = formatApiError(e) }
  finally { starting.value = false }
}

function formatDate(s: string | null) {
  if (!s) return translate('tournaments.notScheduledYet')
  try {
    return new Date(s).toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-GB', { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return s }
}

function playerRange(min: number, max: number | null) {
  return max === null
    ? translate('tournaments.playersPlus', { count: min })
    : translate('tournaments.playersRange', { min, max })
}

function participantMessage(count: number) {
  return translate(count === 1 ? 'tournaments.registeredOne' : 'tournaments.registeredMany', { count })
}

function relativeStart(value: string | null) {
  if (!value) return translate('tournamentOverview.notScheduled')
  const milliseconds = new Date(value).getTime() - Date.now()
  if (!Number.isFinite(milliseconds)) return translate('tournamentOverview.notScheduled')
  const absolute = Math.abs(milliseconds)
  const [amount, unit] = absolute >= 86_400_000
    ? [Math.round(milliseconds / 86_400_000), 'day']
    : absolute >= 3_600_000
      ? [Math.round(milliseconds / 3_600_000), 'hour']
      : [Math.round(milliseconds / 60_000), 'minute']
  return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(amount, unit as Intl.RelativeTimeFormatUnit)
}

function stageModeLabel(mode: string) {
  if (['knockout', 'division', 'groups'].includes(mode)) {
    return translate(`tournamentSettings.stageModes.${mode}`)
  }
  return mode
}

function stageIcon(mode: string) {
  if (mode === 'knockout') return '🏆'
  if (mode === 'division') return '⊞'
  if (mode === 'groups') return '▦'
  return '•'
}

function stageNameById(id: string) {
  return stages.value.find((stage) => stage.id === id)?.name || id
}

function podiumLabel(reference: string, index: number) {
  const stageId = reference.split('.')[0] || ''
  const placement = Number(reference.match(/\d+/)?.[0] ?? index)
  const stageName = stageNameById(stageId)
  if (placement === 0) return translate('tournamentSettings.podium.winner', { stage: stageName })
  if (placement === 1) return translate('tournamentSettings.podium.runnerUp', { stage: stageName })
  if (placement === 2) return translate('tournamentSettings.podium.third', { stage: stageName })
  return translate('tournamentSettings.podium.other', { place: placement + 1, stage: stageName })
}
</script>

<template>
  <div :class="['mx-auto w-full', isOverviewRoute ? 'max-w-6xl' : 'max-w-3xl']">
    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">{{ translate('common.loading') }}</div>
    <div v-else-if="loadFailed" class="mx-auto max-w-xl py-12 text-center">
      <h1 class="text-2xl font-bold text-black">{{ translate('tournamentSettings.unavailable') }}</h1>
      <AppAlert class="mt-4 text-start" type="error" :message="error" />
      <Button as="router-link" to="/tournaments" class="mt-4" :label="translate('common.backTournaments')" severity="contrast" />
    </div>
    <div v-else-if="t" class="space-y-4">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" />
      <header class="workspace-page-heading">
        <div>
          <h2>{{ translate(isSettingsRoute ? 'tournamentWorkspace.settings' : 'tournamentWorkspace.overview') }}</h2>
          <p>{{ translate(isSettingsRoute ? 'tournamentWorkspace.settingsHint' : 'tournamentWorkspace.overviewHint') }}</p>
        </div>
        <p class="workspace-page-heading__creator">
          <span>{{ translate('tournamentSettings.createdBy') }}</span>
          <UserQuickView :user-id="t.creator_id" :username="t.creator || translate('tournamentSettings.unknownUser')" />
        </p>
      </header>

      <TournamentActions
        v-if="isOverviewRoute"
        :tournament-id="t.id"
        :state="t.state"
        :lifecycle-state="t.lifecycle_state"
        :participant-count="t.participant_count"
        :min-players="t.min_players"
        :has-format="hasFormat"
        :starting="starting"
        :publishing="publishing"
        @start="requestStart"
        @publish="publishAndManagePlayers"
      />

      <TournamentOverviewMetrics v-if="isOverviewRoute" :metrics="overviewMetrics" />
      <TournamentAttentionPanel v-if="isOverviewRoute" :items="attentionItems" />

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <p class="mb-4 text-sm font-medium text-zinc-700">{{ participantMessage(t.participant_count) }}</p>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-zinc-50 p-3 text-sm sm:grid-cols-4">
          <TournamentMetaItem :label="translate('tournamentSettings.starts')" :value="formatDate(t.starts_at)" />
          <TournamentMetaItem :label="translate('tournamentSettings.players')" :value="playerRange(t.min_players, t.max_players)" />
          <TournamentMetaItem :label="translate('tournaments.match')" :value="translate('tournaments.raceTo', { points: t.target_points })" />
          <TournamentMetaItem :label="translate('tournaments.timeControl')" :value="translate(`tournaments.${t.time_control === 'none' ? 'noClock' : t.time_control}`)" />
          <TournamentMetaItem :label="translate('tournaments.doubling')" :value="translate(t.doubling_enabled ? 'common.enabled' : 'common.disabled')" />
          <TournamentMetaItem :label="translate('tournaments.entryFee')" :value="Number(t.entry_fee || 0).toFixed(2)" />
          <TournamentMetaItem :label="translate('tournaments.prize')" :value="Number(t.prize_money || 0).toFixed(2)" />
        </dl>
        <div v-if="t.participants?.length" class="mt-4 border-t border-zinc-100 pt-4">
          <div class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">{{ translate('tournamentSettings.registeredPlayers') }}</div>
          <div class="flex flex-wrap gap-2">
            <span v-for="participant in t.participants" :key="participant.id" class="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-700">
              <UserQuickView :user-id="participant.user_id" :username="participant.username || participant.name" />
            </span>
          </div>
        </div>
      </section>

      <!-- Visual editor for stages/podium (draft only) -->
      <div v-if="isSettingsRoute && t.state==='draft'" class="rounded-lg border border-zinc-200 bg-zinc-50 p-4">
        <div class="mb-3 flex items-center justify-between">
          <div><h3 class="text-sm font-semibold text-black">{{ translate('tournamentSettings.draftTitle') }}</h3><p class="text-xs text-zinc-500">{{ translate('tournamentSettings.draftHint') }}</p></div>
          <Button :label="translate(editing ? 'tournamentSettings.closeEditor' : 'tournamentSettings.editDetails')" size="small" :severity="editing ? 'contrast' : 'secondary'" :outlined="!editing" @click="editing = !editing" />
        </div>
        <div v-if="editing" class="mb-4 rounded bg-white border border-zinc-200 p-3 space-y-3">
          <label class="block"><span class="mb-1 block text-xs font-medium text-black">{{ translate('tournamentSettings.name') }}</span><InputText v-model="editName" class="w-full" /></label>
          <TournamentMetaFields :starts-date="editStartsDate" :starts-time="editStartsTime" :time-control="editTime" :min-players="Number(editMin)" :max-players="editMax" :target-points="Number(editPoints)" :doubling-enabled="editDoubling" :entry-fee="editEntryFee" :prize-money="editPrizeMoney" :min-starts-date="minStartsDate" :min-starts-time="minStartsTime" @update:starts-date="editStartsDate=$event" @update:starts-time="editStartsTime=$event" @update:time-control="editTime=$event" @update:min-players="editMin=$event" @update:max-players="editMax=$event" @update:target-points="editPoints=$event" @update:doubling-enabled="editDoubling=$event" @update:entry-fee="editEntryFee=$event" @update:prize-money="editPrizeMoney=$event" />
        </div>
        <h4 class="mb-2 text-xs font-semibold text-zinc-700">{{ translate('tournamentSettings.structure') }}</h4>

        <div v-if="!editing" class="space-y-2">
          <div v-for="s in stages" :key="s.id" class="flex items-center gap-2 rounded bg-white border border-zinc-200 px-3 py-2 text-sm">
            <span class="inline-flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs text-white">{{ stageIcon(s.mode) }}</span>
            <span class="font-medium text-black">{{ s.name }}</span><span class="text-xs text-zinc-500">{{ stageModeLabel(s.mode) }}</span>
          </div>
          <div class="flex flex-wrap gap-1 pt-2">
            <span v-for="(p, i) in podium" :key="i" :title="p" class="rounded-full bg-white border border-zinc-200 px-2 py-1 text-xs">{{ i===0 ? '🥇' : i===1 ? '🥈' : '🥉' }} {{ podiumLabel(p, i) }}</span>
          </div>
        </div>

        <div v-else class="space-y-3">
          <details class="rounded border border-zinc-200 bg-white p-3">
            <summary class="cursor-pointer text-sm font-medium text-black">{{ translate('tournamentSettings.advancedTitle') }}</summary>
            <p class="mt-1 text-xs text-zinc-500">{{ translate('tournamentSettings.advancedHint') }}</p>
            <div class="mt-3 space-y-3">
              <div v-for="(s, idx) in stages" :key="idx" class="grid grid-cols-12 gap-2 rounded border border-zinc-200 p-2">
                <InputText v-model="s.id" :placeholder="translate('tournamentSettings.internalId')" class="col-span-3 text-xs" /><InputText v-model="s.name" :placeholder="translate('tournamentSettings.name')" class="col-span-4 text-xs" /><Select v-model="s.mode" :options="stageModeOptions" option-label="label" option-value="value" class="col-span-3 text-xs" /><Button :label="translate('common.remove')" size="small" severity="danger" text class="col-span-2" @click="removeStage(idx)" />
              </div>
              <Button :label="translate('tournamentSettings.addStage')" size="small" severity="secondary" outlined @click="addStage" />
              <div v-for="(p, i) in podium" :key="i" class="flex items-center gap-2"><span class="w-16 text-xs font-medium">{{ translate('tournamentSettings.place', { place: i + 1 }) }}</span><Select :model-value="p.split('.')[0]" :options="stages" option-label="name" option-value="id" class="min-w-40 text-xs" @update:model-value="podium[i] = `${String($event)}.placements[${p.match(/\d+/)?.[0] ?? '0'}]`" /><Button :label="translate('common.remove')" size="small" severity="danger" text @click="podium.splice(i,1)" /></div>
              <Button :label="translate('tournamentSettings.addPodiumPlace')" size="small" severity="secondary" outlined @click="addPodium" />
              <details><summary class="cursor-pointer text-xs text-zinc-600">{{ translate('tournamentSettings.editYaml') }}</summary><Textarea v-model="editYaml" rows="8" class="mt-2 w-full font-mono text-xs text-black" /></details>
            </div>
          </details>

        </div>
      </div>

      <TournamentStructureCard v-else :stages="stages" />

      <div class="flex flex-wrap gap-2">
        <template v-if="t.state==='draft'">
          <Button v-if="isSettingsRoute" data-testid="publish-and-add" :label="translate('tournamentSettings.publishAndAdd')" severity="success" :loading="publishing" :disabled="!hasFormat" @click="publishAndManagePlayers" />
          <Button data-testid="delete-draft" :label="translate('tournamentDanger.deleteAction')" severity="danger" @click="requestDelete" />
        </template>
        <template v-if="t.state==='open'">
          <Button data-testid="revert-to-draft" class="ms-auto" :label="translate('tournamentDanger.revertAction')" severity="secondary" outlined @click="requestRevertToDraft" />
        </template>
      </div>
    </div>
    <StartTournamentDialog
      v-if="showStartDialog && t" :name="t.name" :participant-count="t.participant_count"
      :busy="starting" :error="startError" @confirm="start" @cancel="showStartDialog = false"
    />
    <TournamentDangerDialog
      v-if="showRevertDialog && t" mode="revert" :name="t.name" :entry-fee="t.entry_fee"
      :busy="reverting" :error="revertError" @confirm="revertToDraft" @cancel="showRevertDialog = false"
    />
    <TournamentDangerDialog
      v-if="showDeleteDialog && t" mode="delete" :name="t.name"
      :busy="deleting" :error="deleteError" @confirm="deleteDraft" @cancel="showDeleteDialog = false"
    />
  </div>
</template>

<style scoped>
.workspace-page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
  padding-bottom: 16px;
  border-bottom: 1px solid #263653;
}
.workspace-page-heading h2 { color: #eef3ff; font-size: 21px; font-weight: 700; }
.workspace-page-heading p { margin-top: 4px; color: #aab8d4; font-size: 12px; }
.workspace-page-heading__creator { display: flex; align-items: center; gap: 5px; }
</style>
