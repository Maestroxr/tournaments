<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppInput from '@/components/AppInput.vue'
import AppAlert from '@/components/AppAlert.vue'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import { apiFetch, formatApiError } from '@/services/api'

const router = useRouter()
const name = ref('')
const template = ref<'division' | 'knockout' | 'groups-knockout'>('knockout')
const startsDate = ref('')
const startsTime = ref('')
const startsAt = computed(() => startsDate.value ? `${startsDate.value}T${startsTime.value || '00:00'}` : '')
const minPlayers = ref(6)
const maxPlayers = ref<number | ''>('')
const previewPlayers = ref(6)
const targetPoints = ref(5)
const timeControl = ref('normal')
const error = ref('')
const submitted = ref(false)
const loading = ref(false)

const templateOptions = [
  { id: 'knockout', label: 'Knockout', description: 'One loss eliminates a player.', bestFor: 'Fast, decisive events', icon: '🏆' },
  { id: 'division', label: 'League', description: 'Every player meets every other player.', bestFor: 'Fair ranking, more games', icon: '⊞' },
  { id: 'groups-knockout', label: 'Groups + Knockout', description: 'Group play followed by elimination rounds.', bestFor: 'Larger events', icon: '▦' },
] as const

const fieldErrors = computed(() => {
  const errors: Record<string, string> = {}
  const min = Number(minPlayers.value)
  const max = maxPlayers.value === '' ? null : Number(maxPlayers.value)
  if (!name.value.trim()) errors.name = 'Enter a tournament name.'
  if (!Number.isInteger(min) || min < 2) errors.min_players = 'Minimum must be at least 2.'
  if (max !== null && (!Number.isInteger(max) || max < 2)) errors.max_players = 'Maximum must be at least 2.'
  if (max !== null && max < min) errors.max_players = 'Maximum cannot be lower than minimum.'
  if (!Number.isInteger(Number(targetPoints.value)) || Number(targetPoints.value) < 1) errors.target_points = 'Match length must be at least 1 point.'
  if (startsAt.value) {
    const date = new Date(startsAt.value)
    if (Number.isNaN(date.getTime())) errors.starts_at = 'Enter a valid date and time.'
    else if (date.getTime() < Date.now() - 60_000) errors.starts_at = 'Start time must be in the future.'
  }
  return errors
})
const visibleErrors = computed(() => submitted.value ? fieldErrors.value : {})
const selectedFormat = computed(() => templateOptions.find(option => option.id === template.value)!)
const effectivePreviewPlayers = computed(() => {
  const min = Math.max(2, Number(minPlayers.value) || 2)
  const max = maxPlayers.value === '' ? Math.max(min, 64) : Math.max(min, Number(maxPlayers.value) || min)
  return Math.min(max, Math.max(min, Number(previewPlayers.value) || min))
})
watch([minPlayers, maxPlayers], () => { previewPlayers.value = effectivePreviewPlayers.value })

function roundNames(rounds: number) {
  const names = ['Final', 'Semifinals', 'Quarterfinals', 'Round of 16', 'Round of 32', 'Round of 64']
  return Array.from({ length: rounds }, (_, index) => names[rounds - index - 1] || `Round ${index + 1}`)
}

const preview = computed(() => {
  const players = effectivePreviewPlayers.value
  if (template.value === 'division') return { players, rounds: Math.max(1, players - 1), matches: players * (players - 1) / 2, byes: 0, stages: ['League standings'] }
  if (template.value === 'groups-knockout') {
    const knockoutPlayers = Math.max(2, 2 ** Math.floor(Math.log2(players)))
    const rounds = Math.ceil(Math.log2(knockoutPlayers))
    return { players, rounds, matches: null, byes: 0, stages: ['Group stage', ...roundNames(rounds)] }
  }
  const rounds = Math.ceil(Math.log2(Math.max(2, players)))
  return { players, rounds, matches: players - 1, byes: 2 ** rounds - players, stages: roundNames(rounds) }
})
const playerRangeText = computed(() => maxPlayers.value === '' ? `The tournament may start with ${minPlayers.value} or more registered players.` : `The tournament may start with any number between ${minPlayers.value} and ${maxPlayers.value}.`)

async function create() {
  submitted.value = true
  error.value = ''
  if (Object.keys(fieldErrors.value).length) { error.value = 'Review the highlighted fields before creating the draft.'; return }
  loading.value = true
  try {
    const created = await apiFetch<{ id: number }>('/api/admin/tournaments', {
      method: 'POST', body: JSON.stringify({ name: name.value.trim(), template: template.value, starts_at: startsAt.value || null, min_players: Number(minPlayers.value), max_players: maxPlayers.value === '' ? null : Number(maxPlayers.value), target_points: Number(targetPoints.value), time_control: timeControl.value }),
    })
    router.push({ name: 'tournament-detail', params: { id: created.id } })
  } catch (caught: unknown) { error.value = formatApiError(caught) } finally { loading.value = false }
}
</script>

<template>
  <div class="mx-auto w-full max-w-4xl">
    <header class="mb-7"><h1 class="text-2xl font-bold text-black">Create a tournament</h1><p class="mt-1 text-sm text-zinc-600">Set the rules, review what will happen, then create a private draft.</p></header>
    <AppAlert v-if="error" class="mb-5" type="error" :message="error" dismissible @close="error = ''" />
    <form class="space-y-5" @submit.prevent="create">
      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <div class="mb-4 flex items-center gap-3"><span class="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-bold text-white">1</span><div><h2 class="font-semibold text-black">Basics</h2><p class="text-xs text-zinc-500">Name and schedule</p></div></div>
        <div class="grid gap-4 sm:grid-cols-2">
          <AppInput v-model="name" label="Tournament name" placeholder="e.g. Jerusalem Open" :error="visibleErrors.name" />
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-sm font-medium">Date <span class="font-normal text-zinc-400">(optional)</span></span><input v-model="startsDate" type="date" :class="['w-full rounded border px-3 py-2 text-sm', visibleErrors.starts_at ? 'border-red-500' : 'border-zinc-300']" /></label>
            <label class="block"><span class="mb-1 block text-sm font-medium">Time</span><input v-model="startsTime" type="time" :disabled="!startsDate" class="w-full rounded border border-zinc-300 px-3 py-2 text-sm disabled:bg-zinc-100" /><span v-if="visibleErrors.starts_at" class="mt-1 block text-xs text-red-600">{{ visibleErrors.starts_at }}</span></label>
          </div>
        </div>
      </section>

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <div class="mb-4 flex items-center gap-3"><span class="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-bold text-white">2</span><div><h2 class="font-semibold text-black">Tournament format</h2><p class="text-xs text-zinc-500">How players advance and are eliminated</p></div></div>
        <div class="grid gap-3 sm:grid-cols-3">
          <button v-for="option in templateOptions" :key="option.id" type="button" :class="['rounded-xl border p-4 text-left transition', template === option.id ? 'border-emerald-600 bg-emerald-50 ring-1 ring-emerald-600' : 'border-zinc-200 hover:border-zinc-400']" @click="template = option.id">
            <div class="mb-2 flex items-center justify-between"><span class="text-xl">{{ option.icon }}</span><span v-if="template === option.id" class="text-xs font-semibold text-emerald-700">Selected</span></div><div class="font-semibold text-black">{{ option.label }}</div><p class="mt-1 text-xs text-zinc-600">{{ option.description }}</p><p class="mt-2 text-xs font-medium text-zinc-500">Best for: {{ option.bestFor }}</p>
          </button>
        </div>
      </section>

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <div class="mb-4 flex items-center gap-3"><span class="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-bold text-white">3</span><div><h2 class="font-semibold text-black">Players</h2><p class="text-xs text-zinc-500">Start threshold and registration capacity</p></div></div>
        <div class="grid gap-4 sm:grid-cols-2">
          <label><span class="mb-1 block text-sm font-medium">Minimum players to start</span><input v-model.number="minPlayers" type="number" min="2" :class="['w-full rounded border px-3 py-2 text-sm', visibleErrors.min_players ? 'border-red-500' : 'border-zinc-300']" /><span v-if="visibleErrors.min_players" class="text-xs text-red-600">{{ visibleErrors.min_players }}</span></label>
          <label><span class="mb-1 block text-sm font-medium">Registration capacity <span class="font-normal text-zinc-400">(optional)</span></span><input v-model="maxPlayers" type="number" min="2" placeholder="No limit" :class="['w-full rounded border px-3 py-2 text-sm', visibleErrors.max_players ? 'border-red-500' : 'border-zinc-300']" /><span v-if="visibleErrors.max_players" class="text-xs text-red-600">{{ visibleErrors.max_players }}</span></label>
        </div><p class="mt-4 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-900">{{ playerRangeText }}</p>
      </section>

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <div class="mb-4 flex items-center gap-3"><span class="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-bold text-white">4</span><div><h2 class="font-semibold text-black">Match rules</h2><p class="text-xs text-zinc-500">Scoring and clock settings</p></div></div>
        <TournamentMetaFields v-model:time-control="timeControl" v-model:target-points="targetPoints" rules-only :errors="visibleErrors" />
      </section>

      <section class="rounded-xl border border-zinc-200 bg-zinc-50 p-5">
        <div class="mb-4 flex items-center gap-3"><span class="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-600 text-xs font-bold text-white">5</span><div><h2 class="font-semibold text-black">Review</h2><p class="text-xs text-zinc-500">Preview the structure before creating the draft</p></div></div>
        <div class="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
          <dl class="grid grid-cols-2 gap-3 text-sm"><div><dt class="text-xs text-zinc-500">Format</dt><dd class="font-medium text-black">{{ selectedFormat.label }}</dd></div><div><dt class="text-xs text-zinc-500">Match</dt><dd class="font-medium text-black">Race to {{ targetPoints }} points</dd></div><div><dt class="text-xs text-zinc-500">Players</dt><dd class="font-medium text-black">{{ minPlayers }}–{{ maxPlayers || 'No limit' }}</dd></div><div><dt class="text-xs text-zinc-500">Schedule</dt><dd class="font-medium text-black">{{ startsAt || 'Not scheduled' }}</dd></div></dl>
          <div class="rounded-lg border border-zinc-200 bg-white p-4">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h3 class="text-sm font-semibold text-black">Structure preview</h3><p class="text-xs text-zinc-500">The final bracket uses the actual player count at Start.</p></div><label class="flex items-center gap-2 text-xs text-zinc-600">Preview with <input v-model.number="previewPlayers" type="number" :min="Math.max(2, Number(minPlayers) || 2)" :max="maxPlayers || 64" class="w-16 rounded border border-zinc-300 px-2 py-1 text-black" /> players</label></div>
            <div class="flex flex-wrap items-center gap-2" aria-label="Tournament progression preview"><template v-for="(stage, index) in preview.stages" :key="stage"><div class="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-center"><div class="text-xs font-semibold text-black">{{ stage }}</div><div class="text-[11px] text-zinc-500">{{ index === 0 ? `${preview.players} players` : 'Winners advance' }}</div></div><span v-if="index < preview.stages.length - 1" class="text-zinc-400">→</span></template></div>
            <p class="mt-3 text-xs text-zinc-600"><template v-if="preview.matches !== null">{{ preview.matches }} matches · </template>{{ preview.rounds }} rounds<span v-if="preview.byes"> · {{ preview.byes }} first-round byes</span><span v-else-if="template === 'knockout'"> · no byes</span></p>
          </div>
        </div>
      </section>

      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 pt-5"><p class="text-xs text-zinc-500">Nothing is published yet. You will add players and review the draft next.</p><div class="flex gap-2"><button type="button" class="rounded border border-zinc-300 bg-white px-4 py-2 text-sm" @click="router.push('/tournaments')">Cancel</button><button type="submit" :disabled="loading" class="rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">{{ loading ? 'Creating draft…' : 'Create draft and add players' }}</button></div></div>
    </form>
  </div>
</template>
