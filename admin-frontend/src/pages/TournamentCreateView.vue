<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import AppInput from '@/components/AppInput.vue'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import { apiFetch } from '@/services/api'

const router = useRouter()
const name = ref('')
const template = ref<'division' | 'knockout' | 'groups-knockout'>('division')
const starts_date = ref('')
const starts_time = ref('')
const starts_at = computed(() => (starts_date.value && starts_time.value ? `${starts_date.value}T${starts_time.value}` : starts_date.value ? `${starts_date.value}T00:00` : ''))
const min_players = ref(6)
const max_players = ref<number | ''>('')
const target_points = ref(5)
const time_control = ref<string>('normal')
const error = ref('')
const loading = ref(false)

const templateOptions = [
  { id: 'division', label: 'Division', desc: 'Round-robin, all play all', icon: '⊞' },
  { id: 'knockout', label: 'Knockout', desc: 'Single elimination', icon: '🏆' },
  { id: 'groups-knockout', label: 'Groups → Knockout', desc: 'Preliminaries + Main Round', icon: '▦' },
] as const

const preview = computed(() => {
  const n = max_players.value === '' || max_players.value === null ? Number(min_players.value) : Number(max_players.value)
  const roundsFor = (players: number) => Math.ceil(Math.log2(Math.max(2, players)))
  const roundsText = (players: number, mode: string) => {
    if (mode === 'division') return `${Math.max(0, players - 1)} rounds (round-robin)`
    return `${roundsFor(players)} rounds`
  }
  if (template.value === 'division') {
    const r = n ? roundsText(n, 'division') : '— rounds'
    return {
      stages: [{ id: 'division', name: 'Division', mode: `division • ${r}` }],
      podium: ['1st Division', '2nd Division', '3rd Division'],
      note: `Division play. ${r}. Played by: All attendees`,
    }
  }
  if (template.value === 'knockout') {
    const r = n ? roundsText(n, 'knockout') : '— rounds'
    // 4 players = 2 rounds (SF + Final), 8 = 3, 16 = 4
    return {
      stages: [{ id: 'main_round', name: 'Main Round', mode: `knockout • ${r}` }],
      podium: ['1st Main Round', '2nd Main Round'],
      note: `Single elimination • ${r}${n ? ` for ${n} players` : ''}`,
    }
  }
  return {
    stages: [
      { id: 'preliminaries', name: 'Preliminaries', mode: `groups (3-4 per group)` },
      { id: 'main_round', name: 'Main Round', mode: `knockout • ${n ? roundsText(n, 'knockout') + ' total' : ''}` },
    ],
    podium: ['1st Main Round', '2nd Main Round'],
    note: `Preliminaries → Main Round ${n ? `• ${roundsText(n, 'knockout')} total` : ''}`,
  }
})

const fieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  const min = Number(min_players.value)
  const max = max_players.value === '' || max_players.value === null ? null : Number(max_players.value)
  const pts = Number(target_points.value)
  if (!min || min < 2) errs.min_players = 'Min ≥2'
  if (max !== null && (isNaN(max) || max < 2)) errs.max_players = 'Max ≥2'
  if (max !== null && min && max < min) errs.max_players = 'Max must be ≥ min'
  if (!pts || pts < 1) errs.target_points = 'Points ≥1'
  if (starts_at.value) {
    const d = new Date(starts_at.value)
    if (isNaN(d.getTime())) errs.starts_at = 'Invalid date'
    else if (d.getTime() < Date.now() - 60000) errs.starts_at = 'Starts at must be future'
  }
  if (!name.value.trim()) errs.name = 'Name required'
  return errs
})
const hasFieldErrors = computed(() => Object.keys(fieldErrors.value).length > 0)

async function create() {
  error.value = ''
  if (hasFieldErrors.value) {
    error.value = Object.values(fieldErrors.value).join(' • ')
    return
  }
  loading.value = true
  try {
    await apiFetch('/api/admin/tournaments', {
      method: 'POST',
      body: JSON.stringify({
        name: name.value.trim(),
        template: template.value,
        starts_at: starts_at.value || null,
        min_players: Number(min_players.value) || 6,
        max_players: max_players.value === '' ? null : Number(max_players.value),
        target_points: Number(target_points.value) || 5,
        time_control: time_control.value,
      }),
    })
    router.push('/tournaments')
  } catch (e: unknown) {
    if (e instanceof Error) {
      try {
        const body = JSON.parse((e as { body?: string }).body || '{}')
        error.value = body.errors ? JSON.stringify(body.errors) : body.detail || e.message
      } catch {
        error.value = e.message
      }
    } else {
      error.value = 'Failed to create tournament'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-3xl">
    <h1 class="mb-1 text-2xl font-bold text-black">Create Tournament</h1>
    <p class="mb-6 text-sm text-zinc-600">YAML still powers the engine — but you configure knockout, times, players & points here.</p>
    <form @submit.prevent="create" class="space-y-6">
      <AppInput v-model="name" label="Tournament name" placeholder="e.g. Spring Championship" :error="error" />

      <div>
        <label class="mb-2 block text-sm font-medium text-zinc-700">Knockout / Mode Template</label>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <button
            v-for="opt in templateOptions"
            :key="opt.id"
            type="button"
            :class="[
              'rounded-lg border p-3 text-left transition',
              template === opt.id ? 'border-zinc-900 bg-zinc-900 text-white' : 'border-zinc-200 bg-white hover:border-zinc-300 text-black',
            ]"
            @click="template = opt.id as typeof template"
          >
            <div class="text-sm font-semibold">{{ opt.icon }} {{ opt.label }}</div>
            <div :class="['text-xs', template === opt.id ? 'text-zinc-300' : 'text-zinc-500']">{{ opt.desc }}</div>
          </button>
        </div>
      </div>

      <TournamentMetaFields
        :starts-date="starts_date"
        :starts-time="starts_time"
        :time-control="time_control"
        :min-players="min_players"
        :max-players="max_players"
        :target-points="target_points"
        :errors="fieldErrors"
        @update:starts-date="starts_date = $event"
        @update:starts-time="starts_time = $event"
        @update:time-control="time_control = $event"
        @update:min-players="min_players = $event"
        @update:max-players="max_players = $event"
        @update:target-points="target_points = $event"
      />

      <!-- Preview -->
      <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-4">
        <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Preview (YAML generated)</div>
        <div class="space-y-2 text-sm text-black">
          <div v-for="s in preview.stages" :key="s.id" class="rounded bg-white p-2 border border-zinc-200">
            <span class="font-medium">{{ s.name }}</span> <span class="text-zinc-500">— {{ s.mode }}</span>
          </div>
          <div class="text-xs text-zinc-600">{{ preview.note }} • {{ target_points }} pts • {{ time_control }} • {{ min_players }}–{{ max_players || '∞' }} players<span v-if="starts_at"> • {{ starts_at }}</span></div>
          <div class="flex gap-2 text-xs">
            <span v-for="p in preview.podium" :key="p" class="rounded-full bg-white border border-zinc-200 px-2 py-1">{{ p }}</span>
          </div>
        </div>
      </div>

      <div class="flex gap-2">
        <button
          type="submit"
          :disabled="loading"
          class="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {{ loading ? 'Creating…' : 'Create Tournament' }}
        </button>
        <button
          type="button"
          class="rounded border border-zinc-300 bg-white px-4 py-2 text-sm text-black hover:bg-zinc-50"
          @click="router.push('/tournaments')"
        >
          Cancel
        </button>
      </div>
    </form>
  </div>
</template>
