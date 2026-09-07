<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import DatePicker from 'primevue/datepicker'
import InputNumber from 'primevue/inputnumber'
import AppAlert from '@/components/AppAlert.vue'
import AppInput from '@/components/AppInput.vue'
import AppStepProgress from '@/components/AppStepProgress.vue'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import { useI18n } from '@/i18n'
import { apiFetch, formatApiError } from '@/services/api'

const router = useRouter()
const { direction, locale, t } = useI18n()
const name = ref('')
const template = ref<'division' | 'knockout' | 'groups-knockout'>('knockout')
const pad = (value: number) => String(value).padStart(2, '0')
const dateInputValue = (date: Date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const timeInputValue = (date: Date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`
const parseLocalDate = (value: string) => {
  const [year, month, day] = value.split('-').map(Number)
  return year && month && day ? new Date(year, month - 1, day) : null
}
const parseLocalTime = (value: string) => {
  const parts = value.split(':').map(Number)
  const hours = parts[0] ?? Number.NaN
  const minutes = parts[1] ?? Number.NaN
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return date
}

const now = new Date()
now.setMinutes(now.getMinutes() + 5, 0, 0)
const minStartsDate = ref(dateInputValue(now))
const minStartsTime = ref(timeInputValue(now))
const startsDate = ref(minStartsDate.value)
const startsTime = ref(minStartsTime.value)
const startsAt = computed(() =>
  startsDate.value ? `${startsDate.value}T${startsTime.value || '00:00'}` : '',
)
const minStartsDateObject = computed(() => parseLocalDate(minStartsDate.value) || new Date())
const minStartsTimeObject = computed(() =>
  startsDate.value === minStartsDate.value
    ? parseLocalTime(minStartsTime.value) || undefined
    : undefined,
)
const startsDateObject = computed<Date | null>({
  get: () => parseLocalDate(startsDate.value),
  set: (value) => {
    startsDate.value = value ? dateInputValue(value) : ''
  },
})
const startsTimeObject = computed<Date | null>({
  get: () => parseLocalTime(startsTime.value),
  set: (value) => {
    startsTime.value = value ? timeInputValue(value) : ''
  },
})

const minPlayers = ref(6)
const maxPlayers = ref<number | ''>(16)
const previewPlayers = ref(6)
const targetPoints = ref(5)
const timeControl = ref('normal')
const doublingEnabled = ref(true)
const entryFee = ref(0)
const prizeMoney = ref(0)
const error = ref('')
const suggestionError = ref('')
const appliedSuggestion = ref('')
const selectedPresetId = ref<string | null>(null)
const submitted = ref(false)
const stepAttempted = ref(false)
const currentStep = ref(1)
const maxVisitedStep = ref(1)
watch(currentStep, () => {
  appliedSuggestion.value = ''
})
const pageTop = ref<HTMLElement | null>(null)
const loading = ref(false)
const createdTournamentId = ref<number | null>(null)
const loadingSuggestions = ref(false)

type ExistingTournament = {
  id: number
  name: string
  state: string
  min_players?: number
  max_players?: number | null
  target_points?: number
  time_control?: string
  doubling_enabled?: boolean
  entry_fee?: string | number
  prize_money?: string | number
}

type TournamentSuggestion = { tournament: ExistingTournament; key: string }
type QuickPreset = {
  id: string
  icon: string
  template: 'division' | 'knockout' | 'groups-knockout'
  minPlayers: number
  maxPlayers: number
  targetPoints: number
  timeControl: string
}

const existingTournaments = ref<ExistingTournament[]>([])
const templateOptions = computed(() => [
  {
    id: 'knockout' as const,
    label: t('tournamentCreate.knockout'),
    description: t('tournamentCreate.knockoutShort'),
    icon: 'bi-trophy',
  },
  {
    id: 'division' as const,
    label: t('tournamentCreate.league'),
    description: t('tournamentCreate.leagueShort'),
    icon: 'bi-table',
  },
  {
    id: 'groups-knockout' as const,
    label: t('tournamentCreate.groups'),
    description: t('tournamentCreate.groupsShort'),
    icon: 'bi-diagram-3',
  },
])
const quickPresets: QuickPreset[] = [
  {
    id: 'quick',
    icon: 'bi-lightning-charge-fill',
    template: 'knockout',
    minPlayers: 4,
    maxPlayers: 8,
    targetPoints: 3,
    timeControl: 'fast',
  },
  {
    id: 'club',
    icon: 'bi-people',
    template: 'knockout',
    minPlayers: 6,
    maxPlayers: 16,
    targetPoints: 5,
    timeControl: 'normal',
  },
  {
    id: 'large',
    icon: 'bi-trophy',
    template: 'groups-knockout',
    minPlayers: 16,
    maxPlayers: 32,
    targetPoints: 7,
    timeControl: 'normal',
  },
]
watch([template, minPlayers, maxPlayers, targetPoints, timeControl], () => {
  const preset = quickPresets.find((item) => item.id === selectedPresetId.value)
  if (!preset) return
  const stillMatches =
    template.value === preset.template &&
    Number(minPlayers.value) === preset.minPlayers &&
    Number(maxPlayers.value) === preset.maxPlayers &&
    Number(targetPoints.value) === preset.targetPoints &&
    timeControl.value === preset.timeControl
  if (!stillMatches) selectedPresetId.value = null
})
const steps = computed(() => [
  { id: 1, number: 1, label: t('tournamentCreate.steps.basics'), icon: 'bi-calendar-event' },
  { id: 2, number: 2, label: t('tournamentCreate.steps.format'), icon: 'bi-diagram-3' },
  { id: 3, number: 3, label: t('tournamentCreate.steps.rules'), icon: 'bi-sliders' },
  { id: 4, number: 4, label: t('tournamentCreate.steps.review'), icon: 'bi-check2-circle' },
])
const completedStepIds = computed(() =>
  steps.value.filter((step) => isStepComplete(step.number)).map((step) => step.id),
)
const selectableStepIds = computed(() =>
  steps.value.filter((step) => step.number <= maxVisitedStep.value).map((step) => step.id),
)

const fieldErrors = computed(() => {
  const errors: Record<string, string> = {}
  const min = Number(minPlayers.value)
  const max = maxPlayers.value === '' ? null : Number(maxPlayers.value)
  if (!name.value.trim()) errors.name = t('tournamentCreate.nameRequired')
  if (!Number.isInteger(min) || min < 2) errors.min_players = t('tournamentCreate.minPlayersError')
  if (max !== null && (!Number.isInteger(max) || max < 2))
    errors.max_players = t('tournamentCreate.maxPlayersError')
  if (max !== null && max < min) errors.max_players = t('tournamentCreate.playerRangeError')
  if (!Number.isInteger(Number(targetPoints.value)) || Number(targetPoints.value) < 1)
    errors.target_points = t('tournamentCreate.matchLengthError')
  if (Number.isNaN(Number(entryFee.value)) || Number(entryFee.value) < 0)
    errors.entry_fee = t('tournamentCreate.entryFeeError')
  if (Number.isNaN(Number(prizeMoney.value)) || Number(prizeMoney.value) < 0)
    errors.prize_money = t('tournamentCreate.prizeError')
  if (startsAt.value) {
    const date = new Date(startsAt.value)
    if (Number.isNaN(date.getTime())) errors.starts_at = t('tournamentCreate.dateError')
    else if (date.getTime() < Math.floor(Date.now() / 60_000) * 60_000)
      errors.starts_at = t('tournamentCreate.futureDateError')
  }
  return errors
})
const stepFieldNames: Record<number, string[]> = {
  1: ['name', 'starts_at'],
  2: ['min_players', 'max_players'],
  3: ['target_points', 'entry_fee', 'prize_money'],
}
const currentStepErrors = computed(() =>
  Object.fromEntries(
    Object.entries(fieldErrors.value).filter(([field]) =>
      stepFieldNames[currentStep.value]?.includes(field),
    ),
  ),
)
const visibleErrors = computed(() => {
  if (submitted.value) return fieldErrors.value
  if (!stepAttempted.value) return {}
  return currentStepErrors.value
})
const selectedFormat = computed(() =>
  templateOptions.value.find((option) => option.id === template.value)!,
)
const selectedPreset = computed(
  () => quickPresets.find((preset) => preset.id === selectedPresetId.value) ?? null,
)
const formatIsConfigured = computed(
  () => selectedPreset.value !== null || maxVisitedStep.value >= 2,
)
const rulesAreConfigured = computed(
  () => selectedPreset.value !== null || maxVisitedStep.value >= 3,
)
const nextButtonLabel = computed(() => {
  if (createdTournamentId.value !== null) return t('tournamentCreate.retryRegistration')
  if (currentStep.value === 1) return t('tournamentCreate.continueToFormat')
  if (currentStep.value === 2) return t('tournamentCreate.continueToRules')
  if (currentStep.value === 3) return t('tournamentCreate.continueToReview')
  return t('tournamentCreate.createAndOpen')
})
const nextButtonDisabled = computed(
  () => loading.value || (currentStep.value === 1 && !name.value.trim()),
)
function isStepComplete(step: number) {
  if (step >= maxVisitedStep.value || step === currentStep.value) return false
  const fields = stepFieldNames[step]
  if (!fields) return false
  return !fields.some((field) => field in fieldErrors.value)
}
const normalizeMoney = (value: string | number | undefined) => Number(value ?? 0).toFixed(2)
const settingsKey = (tournament: ExistingTournament) =>
  JSON.stringify({
    min_players: Number(tournament.min_players ?? 6),
    max_players: tournament.max_players ?? null,
    target_points: Number(tournament.target_points ?? 5),
    time_control: tournament.time_control ?? 'normal',
    doubling_enabled: tournament.doubling_enabled !== false,
    entry_fee: normalizeMoney(tournament.entry_fee),
    prize_money: normalizeMoney(tournament.prize_money),
  })
const tournamentSuggestions = computed<TournamentSuggestion[]>(() => {
  const bySettings = new Map<string, TournamentSuggestion>()
  for (const tournament of existingTournaments.value) {
    const key = settingsKey(tournament)
    if (!bySettings.has(key)) bySettings.set(key, { tournament, key })
  }
  return [...bySettings.values()].slice(0, 6)
})
const hasTournamentSuggestions = computed(() => tournamentSuggestions.value.length > 0)
const maxPlayersModel = computed<number | null>({
  get: () => (maxPlayers.value === '' ? null : Number(maxPlayers.value)),
  set: (value) => {
    maxPlayers.value = value === null ? '' : value
  },
})
const effectivePreviewPlayers = computed(() => {
  const min = Math.max(2, Number(minPlayers.value) || 2)
  const max =
    maxPlayers.value === '' ? Math.max(min, 64) : Math.max(min, Number(maxPlayers.value) || min)
  return Math.min(max, Math.max(min, Number(previewPlayers.value) || min))
})
watch([minPlayers, maxPlayers], () => {
  previewPlayers.value = effectivePreviewPlayers.value
})

function roundNames(rounds: number) {
  const names = [
    t('tournamentCreate.final'),
    t('tournamentCreate.semifinals'),
    t('tournamentCreate.quarterfinals'),
    t('tournamentCreate.round16'),
    t('tournamentCreate.round32'),
    t('tournamentCreate.round64'),
  ]
  return Array.from(
    { length: rounds },
    (_, index) => names[rounds - index - 1] || t('tournamentCreate.round', { number: index + 1 }),
  )
}

const preview = computed(() => {
  const players = effectivePreviewPlayers.value
  if (template.value === 'division')
    return {
      players,
      rounds: Math.max(1, players - 1),
      matches: (players * (players - 1)) / 2,
      byes: 0,
      stages: [t('tournamentCreate.leagueTable')],
    }
  if (template.value === 'groups-knockout') {
    const knockoutPlayers = Math.max(2, 2 ** Math.floor(Math.log2(players)))
    const rounds = Math.ceil(Math.log2(knockoutPlayers))
    return {
      players,
      rounds,
      matches: null,
      byes: 0,
      stages: [t('tournamentCreate.groupStage'), ...roundNames(rounds)],
    }
  }
  const rounds = Math.ceil(Math.log2(Math.max(2, players)))
  return {
    players,
    rounds,
    matches: players - 1,
    byes: 2 ** rounds - players,
    stages: roundNames(rounds),
  }
})
const playerRangeText = computed(() =>
  maxPlayers.value === ''
    ? t('tournamentCreate.playersUnlimited', { min: minPlayers.value })
    : t('tournamentCreate.playersRange', { min: minPlayers.value, max: maxPlayers.value }),
)
const scheduleText = computed(() => {
  if (!startsAt.value) return t('tournaments.notScheduled')
  const value = new Date(startsAt.value)
  if (Number.isNaN(value.getTime())) return startsAt.value
  return new Intl.DateTimeFormat(locale.value === 'he' ? 'he-IL' : 'en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(value)
})

function applyPreset(preset: QuickPreset) {
  template.value = preset.template
  minPlayers.value = preset.minPlayers
  maxPlayers.value = preset.maxPlayers
  targetPoints.value = preset.targetPoints
  timeControl.value = preset.timeControl
  doublingEnabled.value = true
  entryFee.value = 0
  prizeMoney.value = 0
  selectedPresetId.value = preset.id
  appliedSuggestion.value = t(`tournamentCreate.presetApplied.${preset.id}`)
}

function applySuggestion(tournament: ExistingTournament) {
  selectedPresetId.value = null
  minPlayers.value = Number(tournament.min_players ?? 6)
  maxPlayers.value = tournament.max_players == null ? '' : Number(tournament.max_players)
  targetPoints.value = Number(tournament.target_points ?? 5)
  timeControl.value = tournament.time_control ?? 'normal'
  doublingEnabled.value = tournament.doubling_enabled !== false
  entryFee.value = Number(tournament.entry_fee ?? 0)
  prizeMoney.value = Number(tournament.prize_money ?? 0)
  appliedSuggestion.value = t('tournamentCreate.previousApplied', { name: tournament.name })
}

function describeSuggestion(tournament: ExistingTournament) {
  const max = tournament.max_players == null ? t('tournaments.unlimited') : tournament.max_players
  return [
    t('tournamentCreate.suggestionPlayers', { min: tournament.min_players ?? 6, max }),
    t('tournaments.raceTo', { points: tournament.target_points ?? 5 }),
    tournament.time_control ?? 'normal',
  ].join(' · ')
}

async function loadExistingTournaments() {
  loadingSuggestions.value = true
  suggestionError.value = ''
  try {
    existingTournaments.value = await apiFetch<ExistingTournament[]>('/api/admin/tournaments')
  } catch (caught: unknown) {
    suggestionError.value = formatApiError(caught)
  } finally {
    loadingSuggestions.value = false
  }
}

onMounted(() => {
  void loadExistingTournaments()
})

async function scrollToStep() {
  await nextTick()
  pageTop.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

async function goNext() {
  stepAttempted.value = true
  error.value = ''
  if (Object.keys(currentStepErrors.value).length) {
    error.value = t('tournamentCreate.completeStep')
    return
  }
  currentStep.value = Math.min(4, currentStep.value + 1)
  maxVisitedStep.value = Math.max(maxVisitedStep.value, currentStep.value)
  stepAttempted.value = false
  await scrollToStep()
}

async function goBack() {
  if (loading.value || createdTournamentId.value !== null) return
  currentStep.value = Math.max(1, currentStep.value - 1)
  stepAttempted.value = false
  error.value = ''
  await scrollToStep()
}

async function goToStep(step: number) {
  if (loading.value || createdTournamentId.value !== null) return
  if (step > maxVisitedStep.value || step === currentStep.value) return
  currentStep.value = step
  stepAttempted.value = false
  error.value = ''
  await scrollToStep()
}

async function handleSubmit() {
  if (currentStep.value < 4) await goNext()
  else await create()
}

async function create() {
  if (loading.value) return
  submitted.value = true
  error.value = ''
  if (createdTournamentId.value === null && Object.keys(fieldErrors.value).length) {
    error.value = t('tournamentCreate.reviewErrors')
    const firstInvalidStep = [1, 2, 3].find((step) =>
      stepFieldNames[step]?.some((field) => fieldErrors.value[field]),
    )
    if (firstInvalidStep) currentStep.value = firstInvalidStep
    return
  }
  loading.value = true
  try {
    if (createdTournamentId.value === null) {
      const created = await apiFetch<{ id: number }>('/api/admin/tournaments', {
        method: 'POST',
        body: JSON.stringify({
          name: name.value.trim(),
          template: template.value,
          starts_at: startsAt.value || null,
          min_players: Number(minPlayers.value),
          max_players: maxPlayers.value === '' ? null : Number(maxPlayers.value),
          target_points: Number(targetPoints.value),
          time_control: timeControl.value,
          doubling_enabled: doublingEnabled.value,
          entry_fee: Number(entryFee.value),
          prize_money: Number(prizeMoney.value),
          open_registration: true,
        }),
      })
      createdTournamentId.value = created.id
    }
    const path = `/api/admin/tournaments/${createdTournamentId.value}`
    // Check persisted state, including when a previous publish succeeded but its response was lost.
    let saved = await apiFetch<{ state: string }>(path)
    if (saved.state === 'draft') {
      await apiFetch(`${path}/publish`, { method: 'POST' })
      saved = await apiFetch<{ state: string }>(path)
    }
    if (!['open', 'active', 'finished'].includes(saved.state)) {
      throw new Error(t('tournamentCreate.registrationNotOpen'))
    }
    await router.push({ name: 'tournament-detail', params: { id: createdTournamentId.value } })
  } catch (caught: unknown) {
    error.value =
      createdTournamentId.value === null
        ? formatApiError(caught)
        : `${t('tournamentCreate.registrationRetryHint')} ${formatApiError(caught)}`
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="tournament-create mx-auto w-full max-w-[1180px]">
    <header class="mb-7 flex flex-wrap items-end justify-between gap-5">
      <div>
        <p class="mb-2 text-xs font-bold tracking-[0.12em] text-sky-300 uppercase">
          {{ t('tournamentCreate.quickBadge') }}
        </p>
        <h1 class="m-0 text-3xl font-bold text-black sm:text-4xl">
          {{ t('tournamentCreate.title') }}
        </h1>
        <p class="mt-2 max-w-2xl text-sm text-zinc-600">{{ t('tournamentCreate.subtitle') }}</p>
      </div>
      <Button
        type="button"
        :label="t('common.cancel')"
        severity="secondary"
        text
        @click="router.push('/tournaments')"
      />
    </header>

    <form @submit.prevent="handleSubmit">
      <div ref="pageTop"></div>

      <AppStepProgress
        class="mb-7"
        :steps="steps"
        :current-step="currentStep"
        :completed-steps="completedStepIds"
        :selectable-steps="selectableStepIds"
        :progress-label="
          t('tournamentCreate.stepProgress', { current: currentStep, total: steps.length })
        "
        :label="t('tournamentCreate.wizardTitle')"
        :disabled="loading || createdTournamentId !== null"
        interactive
        @select="goToStep(Number($event))"
      />

      <AppAlert
        v-if="error"
        class="mb-5"
        type="error"
        :message="error"
        dismissible
        @close="error = ''"
      />

      <div
        class="mb-4 flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm lg:hidden"
      >
        <span class="text-zinc-500">{{ t('tournamentCreate.setupSummary') }}</span>
        <strong class="truncate text-black">{{ name || t('tournamentCreate.untitled') }}</strong>
      </div>

      <div class="grid items-start gap-7 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div class="space-y-5">
          <section
            v-if="currentStep === 1"
            class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-7"
          >
            <div class="mb-6 flex items-start gap-3">
              <span
                class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-sky-400/15 text-sky-200"
                ><i class="bi bi-calendar-event" aria-hidden="true"
              /></span>
              <div>
                <h2 class="text-xl font-semibold text-black">
                  {{ t('tournamentCreate.essentials') }}
                </h2>
                <p class="text-sm text-zinc-500">{{ t('tournamentCreate.essentialsHint') }}</p>
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-[minmax(220px,1.35fr)_minmax(280px,1fr)]">
              <AppInput
                v-model="name"
                :label="`${t('tournamentCreate.name')} *`"
                :placeholder="t('tournamentCreate.namePlaceholder')"
                :error="visibleErrors.name"
                autocomplete="off"
              />
              <div class="grid min-w-0 grid-cols-2 gap-3">
                <label class="block min-w-0"
                  ><span class="mb-1 block text-sm font-medium">{{ t('tournaments.date') }}</span
                  ><DatePicker
                    v-model="startsDateObject"
                    date-format="yy-mm-dd"
                    show-icon
                    fluid
                    manual-input
                    :min-date="minStartsDateObject"
                    :invalid="Boolean(visibleErrors.starts_at)"
                /></label>
                <label class="block min-w-0"
                  ><span class="mb-1 block text-sm font-medium">{{ t('tournaments.time') }}</span
                  ><DatePicker
                    v-model="startsTimeObject"
                    time-only
                    hour-format="24"
                    show-icon
                    fluid
                    manual-input
                    :min-date="minStartsTimeObject"
                    :invalid="Boolean(visibleErrors.starts_at)"
                /></label>
                <span v-if="visibleErrors.starts_at" class="col-span-2 text-xs text-red-600">{{
                  visibleErrors.starts_at
                }}</span>
              </div>
            </div>

            <div class="my-7 border-t border-zinc-200" />

            <div class="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 class="text-base font-semibold text-black">
                  {{ t('tournamentCreate.optionalPresetTitle') }}
                </h3>
                <p class="mt-1 text-xs text-zinc-500">
                  {{ t('tournamentCreate.optionalPresetHint') }}
                </p>
              </div>
              <span class="text-xs text-zinc-400">{{ t('tournamentCreate.optional') }}</span>
            </div>
            <div
              class="grid gap-3 sm:grid-cols-3"
              role="group"
              :aria-label="t('tournamentCreate.startPreset')"
            >
              <button
                v-for="preset in quickPresets"
                :key="preset.id"
                type="button"
                :aria-pressed="selectedPresetId === preset.id"
                :class="[
                  'relative min-h-24 rounded-lg border p-4 text-start transition',
                  selectedPresetId === preset.id
                    ? 'border-sky-400 bg-sky-400/10 ring-1 ring-sky-400'
                    : 'border-zinc-200 bg-zinc-50 hover:border-sky-400 hover:bg-sky-400/5',
                ]"
                @click="applyPreset(preset)"
              >
                <i
                  v-if="selectedPresetId === preset.id"
                  class="bi bi-check-circle-fill absolute end-3 top-3 text-sky-300"
                  aria-hidden="true"
                />
                <span class="mb-2 flex items-center gap-2 pe-6 text-sm font-semibold text-black"
                  ><i :class="`bi ${preset.icon} text-sky-300`" aria-hidden="true" />{{
                    t(`tournamentCreate.presets.${preset.id}`)
                  }}</span
                >
                <span class="block text-xs leading-relaxed text-zinc-500">{{
                  t(`tournamentCreate.presetDetails.${preset.id}`)
                }}</span>
              </button>
            </div>
            <p
              v-if="appliedSuggestion"
              role="status"
              class="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700"
            >
              <i class="bi bi-check-circle" aria-hidden="true" /> {{ appliedSuggestion }}
            </p>
          </section>

          <section
            v-if="currentStep === 2"
            class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-7"
          >
            <div class="mb-5 flex items-center gap-3">
              <span
                class="grid h-10 w-10 place-items-center rounded-lg bg-violet-400/15 text-violet-200"
                ><i class="bi bi-diagram-3" aria-hidden="true"
              /></span>
              <div>
                <h2 class="text-xl font-semibold text-black">
                  {{ t('tournamentCreate.chooseFormat') }}
                </h2>
                <p class="text-sm text-zinc-500">{{ t('tournamentCreate.chooseFormatHint') }}</p>
              </div>
            </div>
            <div class="grid gap-3 sm:grid-cols-3">
              <button
                v-for="option in templateOptions"
                :key="option.id"
                type="button"
                :aria-pressed="template === option.id"
                :class="[
                  'relative rounded-xl border p-4 text-start transition',
                  template === option.id
                    ? 'border-sky-400 bg-sky-400/10 ring-1 ring-sky-400'
                    : 'border-zinc-200 bg-zinc-50 hover:border-zinc-400',
                ]"
                @click="template = option.id"
              >
                <i
                  v-if="template === option.id"
                  class="bi bi-check-circle-fill absolute end-3 top-3 text-sky-300"
                  aria-hidden="true"
                /><i
                  :class="`bi ${option.icon} mb-3 block text-xl text-sky-300`"
                  aria-hidden="true"
                />
                <div class="text-sm font-semibold text-black">{{ option.label }}</div>
                <p class="mt-1 text-xs text-zinc-500">{{ option.description }}</p>
              </button>
            </div>

            <div class="mt-6 border-t border-zinc-200 pt-6">
              <div class="mb-4 flex items-center gap-3">
                <span
                  class="grid h-10 w-10 place-items-center rounded-lg bg-emerald-400/15 text-emerald-200"
                  ><i class="bi bi-people" aria-hidden="true"
                /></span>
                <div>
                  <h3 class="text-lg font-semibold text-black">
                    {{ t('tournamentCreate.players') }}
                  </h3>
                  <p class="text-xs text-zinc-500">{{ t('tournamentCreate.playersHint') }}</p>
                </div>
              </div>
              <div class="grid gap-4 sm:grid-cols-2">
                <label
                  ><span class="mb-1 block text-sm font-medium">{{
                    t('tournamentCreate.minimumToStart')
                  }}</span
                  ><InputNumber
                    v-model="minPlayers"
                    :min="2"
                    show-buttons
                    fluid
                    :invalid="Boolean(visibleErrors.min_players)"
                  /><span
                    v-if="visibleErrors.min_players"
                    class="mt-1 block text-xs text-red-600"
                    >{{ visibleErrors.min_players }}</span
                  ></label
                >
                <label
                  ><span class="mb-1 block text-sm font-medium"
                    >{{ t('tournamentCreate.capacity') }}
                    <span class="font-normal text-zinc-400"
                      >({{ t('tournamentCreate.optional') }})</span
                    ></span
                  ><InputNumber
                    v-model="maxPlayersModel"
                    :min="2"
                    :placeholder="t('tournaments.unlimited')"
                    show-buttons
                    fluid
                    :invalid="Boolean(visibleErrors.max_players)"
                  /><span
                    v-if="visibleErrors.max_players"
                    class="mt-1 block text-xs text-red-600"
                    >{{ visibleErrors.max_players }}</span
                  ></label
                >
              </div>
              <p
                class="mt-4 flex items-center gap-2 rounded-lg bg-sky-400/10 px-3 py-2 text-sm text-sky-100"
              >
                <i class="bi bi-info-circle" aria-hidden="true" /> {{ playerRangeText }}
              </p>
            </div>
          </section>

          <section
            v-if="currentStep === 3"
            class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-7"
          >
            <div class="mb-5 flex items-center gap-3">
              <span
                class="grid h-10 w-10 place-items-center rounded-lg bg-amber-400/15 text-amber-200"
                ><i class="bi bi-sliders" aria-hidden="true"
              /></span>
              <div>
                <h2 class="text-xl font-semibold text-black">
                  {{ t('tournamentCreate.advanced') }}
                </h2>
                <p class="text-sm text-zinc-500">
                  {{ t('tournamentCreate.advancedSummary', { points: targetPoints }) }}
                </p>
              </div>
            </div>
            <TournamentMetaFields
              v-model:time-control="timeControl"
              v-model:target-points="targetPoints"
              v-model:doubling-enabled="doublingEnabled"
              v-model:entry-fee="entryFee"
              v-model:prize-money="prizeMoney"
              rules-only
              :errors="visibleErrors"
            />

            <section class="mt-6 border-t border-zinc-200 pt-6">
              <div class="mb-3">
                <strong class="text-sm text-black">{{ t('tournamentCreate.usePrevious') }}</strong>
                <p class="mt-1 text-xs text-zinc-500">
                  {{ t('tournamentCreate.usePreviousHint') }}
                </p>
              </div>
              <p v-if="loadingSuggestions" class="text-sm text-zinc-500">
                {{ t('common.loading') }}
              </p>
              <p
                v-else-if="suggestionError"
                class="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800"
              >
                {{ suggestionError }}
              </p>
              <p v-else-if="!hasTournamentSuggestions" class="text-sm text-zinc-500">
                {{ t('tournamentCreate.noPrevious') }}
              </p>
              <div v-else class="grid gap-2 sm:grid-cols-2">
                <button
                  v-for="suggestion in tournamentSuggestions"
                  :key="suggestion.key"
                  type="button"
                  class="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-start transition hover:border-sky-400"
                  @click="applySuggestion(suggestion.tournament)"
                >
                  <span class="block text-sm font-semibold text-black">{{
                    suggestion.tournament.name
                  }}</span
                  ><span class="mt-1 block text-xs text-zinc-500">{{
                    describeSuggestion(suggestion.tournament)
                  }}</span>
                </button>
              </div>
              <p
                v-if="appliedSuggestion"
                role="status"
                class="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700"
              >
                <i class="bi bi-check-circle" aria-hidden="true" /> {{ appliedSuggestion }}
              </p>
            </section>
          </section>

          <section
            v-if="currentStep === 4"
            class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-7"
          >
            <div class="mb-4">
              <h2 class="text-xl font-semibold text-black">
                {{ t('tournamentCreate.reviewTitle') }}
              </h2>
              <p class="mt-1 text-sm text-zinc-500">{{ t('tournamentCreate.reviewHint') }}</p>
            </div>
            <dl class="space-y-3 text-sm">
              <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                <dt class="text-xs text-zinc-500">{{ t('tournamentCreate.name') }}</dt>
                <dd class="font-semibold text-black">
                  {{ name || t('tournamentCreate.untitled') }}
                </dd>
              </div>
              <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                <dt class="text-xs text-zinc-500">{{ t('tournaments.startTime') }}</dt>
                <dd class="font-semibold text-black">{{ scheduleText }}</dd>
              </div>
              <div class="grid gap-3 sm:grid-cols-2">
                <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                  <dt class="text-xs text-zinc-500">{{ t('tournamentCreate.format') }}</dt>
                  <dd class="font-semibold text-black">{{ selectedFormat.label }}</dd>
                </div>
                <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                  <dt class="text-xs text-zinc-500">{{ t('tournamentCreate.size') }}</dt>
                  <dd class="font-semibold text-black">
                    {{ minPlayers }}–{{ maxPlayers || t('tournaments.unlimited') }}
                  </dd>
                </div>
                <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                  <dt class="text-xs text-zinc-500">{{ t('tournaments.match') }}</dt>
                  <dd class="font-semibold text-black">
                    {{ t('tournaments.raceTo', { points: targetPoints }) }}
                  </dd>
                </div>
                <div class="rounded-lg border border-zinc-100 bg-zinc-50 px-3 py-2">
                  <dt class="text-xs text-zinc-500">{{ t('tournaments.doubling') }}</dt>
                  <dd class="font-semibold text-black">
                    {{ doublingEnabled ? t('common.enabled') : t('common.disabled') }}
                  </dd>
                </div>
              </div>
            </dl>
          </section>

          <footer
            class="flex flex-col-reverse justify-between gap-3 border-t border-zinc-200 pt-5 sm:flex-row"
          >
            <Button
              v-if="currentStep > 1"
              type="button"
              :label="t('tournamentCreate.back')"
              severity="secondary"
              outlined
              :disabled="loading || createdTournamentId !== null"
              @click="goBack"
            />
            <Button
              v-else
              type="button"
              :label="t('common.cancel')"
              severity="secondary"
              text
              @click="router.push('/tournaments')"
            />
            <Button
              type="submit"
              :label="nextButtonLabel"
              :loading="loading"
              :disabled="nextButtonDisabled"
              severity="success"
              icon="bi bi-arrow-right-circle"
              :icon-pos="direction === 'rtl' ? 'right' : 'left'"
            />
          </footer>
        </div>

        <aside class="hidden lg:sticky lg:top-5 lg:block">
          <section class="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
            <div class="border-b border-zinc-200 bg-zinc-50 p-5">
              <p class="text-xs font-semibold tracking-wider text-sky-300 uppercase">
                {{ t('tournamentCreate.setupSummary') }}
              </p>
              <h2 class="mt-1 truncate text-xl font-bold text-black">
                {{ name || t('tournamentCreate.untitled') }}
              </h2>
            </div>
            <div class="space-y-5 p-5">
              <dl class="text-sm">
                <div class="flex items-start justify-between gap-4 border-b border-zinc-200 py-3">
                  <dt class="text-zinc-500">{{ t('tournaments.startTime') }}</dt>
                  <dd class="text-end font-semibold text-black">{{ scheduleText }}</dd>
                </div>
                <div class="flex items-start justify-between gap-4 border-b border-zinc-200 py-3">
                  <dt class="text-zinc-500">{{ t('tournamentCreate.template') }}</dt>
                  <dd
                    class="text-end font-semibold"
                    :class="selectedPreset ? 'text-black' : 'text-zinc-500'"
                  >
                    {{
                      selectedPreset
                        ? t(`tournamentCreate.presets.${selectedPreset.id}`)
                        : t('tournamentCreate.notSelected')
                    }}
                  </dd>
                </div>
                <div class="flex items-start justify-between gap-4 border-b border-zinc-200 py-3">
                  <dt class="text-zinc-500">{{ t('tournamentCreate.format') }}</dt>
                  <dd
                    class="text-end font-semibold"
                    :class="formatIsConfigured ? 'text-black' : 'text-zinc-500'"
                  >
                    {{
                      formatIsConfigured
                        ? selectedFormat.label
                        : t('tournamentCreate.chooseInStep', { step: 2 })
                    }}
                  </dd>
                </div>
                <div class="flex items-start justify-between gap-4 border-b border-zinc-200 py-3">
                  <dt class="text-zinc-500">{{ t('tournamentCreate.size') }}</dt>
                  <dd
                    class="text-end font-semibold"
                    :class="formatIsConfigured ? 'text-black' : 'text-zinc-500'"
                  >
                    {{
                      formatIsConfigured
                        ? `${minPlayers}–${maxPlayers || t('tournaments.unlimited')}`
                        : t('tournamentCreate.chooseInStep', { step: 2 })
                    }}
                  </dd>
                </div>
                <div class="flex items-start justify-between gap-4 py-3">
                  <dt class="text-zinc-500">{{ t('tournaments.match') }}</dt>
                  <dd
                    class="text-end font-semibold"
                    :class="rulesAreConfigured ? 'text-black' : 'text-zinc-500'"
                  >
                    {{
                      rulesAreConfigured
                        ? t('tournaments.raceTo', { points: targetPoints })
                        : t('tournamentCreate.chooseInStep', { step: 3 })
                    }}
                  </dd>
                </div>
              </dl>

              <div v-if="formatIsConfigured">
                <div class="mb-3 flex items-center justify-between gap-2">
                  <h3 class="text-sm font-semibold text-black">
                    {{ t('tournamentCreate.structure') }}
                  </h3>
                  <label class="flex items-center gap-1 text-xs text-zinc-500"
                    ><span>{{ t('tournamentCreate.previewWith') }}</span
                    ><InputNumber
                      v-model="previewPlayers"
                      :min="Math.max(2, Number(minPlayers) || 2)"
                      :max="maxPlayers || 64"
                      input-class="w-14 text-center"
                  /></label>
                </div>
                <div
                  class="flex flex-wrap items-center gap-1.5"
                  :aria-label="t('tournamentCreate.structure')"
                >
                  <template v-for="(stage, index) in preview.stages.slice(0, 4)" :key="stage"
                    ><span
                      class="rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-[11px] font-medium text-black"
                      >{{ stage }}</span
                    ><span
                      v-if="index < Math.min(preview.stages.length, 4) - 1"
                      class="text-zinc-400"
                      >{{ direction === 'rtl' ? '←' : '→' }}</span
                    ></template
                  >
                </div>
                <p class="mt-2 text-xs text-zinc-500">
                  <template v-if="preview.matches !== null"
                    >{{ t('tournamentCreate.matches', { count: preview.matches }) }} · </template
                  >{{ t('tournamentCreate.rounds', { count: preview.rounds })
                  }}<template v-if="preview.byes">
                    · {{ t('tournamentCreate.byes', { count: preview.byes }) }}</template
                  >
                </p>
              </div>

              <div
                class="rounded-lg border border-emerald-400/20 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100"
              >
                <i class="bi bi-shield-check me-1" aria-hidden="true" />
                {{
                  currentStep === 4
                    ? t('tournamentCreate.registrationNotice')
                    : t('tournamentCreate.notPublishedUntilReview')
                }}
              </div>
            </div>
          </section>
        </aside>
      </div>
    </form>
  </div>
</template>
