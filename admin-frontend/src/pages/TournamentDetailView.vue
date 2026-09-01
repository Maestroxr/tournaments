<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import AppAlert from '@/components/AppAlert.vue'
import TournamentMetaItem from '@/components/TournamentMetaItem.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import * as yaml from 'js-yaml'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
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
  creator: string | null
  creator_id: number | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
  definition: string
  participants: TournamentParticipant[]
  published: boolean
}
const t = ref<TournamentDetail | null>(null)
const editing = ref(false)
const saving = ref(false)
const editYaml = ref('')

interface Stage { id: string; name: string; mode: string }
const stages = ref<Stage[]>([])
const podium = ref<string[]>([])
const editName = ref('')
const editStartsDate = ref('')
const editStartsTime = ref('')
const editMin = ref(6)
const editMax = ref<number | ''>('')
const editPoints = ref(5)
const editTime = ref('normal')

const readinessItems = computed(() => {
  if (!t.value) return []
  const hasFormat = stages.value.length > 0 && podium.value.length > 0
  const enoughPlayers = t.value.participant_count >= t.value.min_players
  return [
    { label: 'Tournament details completed', done: Boolean(t.value.name && t.value.target_points >= 1) },
    { label: 'Tournament format validated', done: hasFormat },
    { label: `${t.value.participant_count} of ${t.value.min_players} required players registered`, done: enoughPlayers },
    { label: 'Tournament published', done: t.value.published },
    { label: 'Ready to start', done: t.value.state === 'open' && enoughPlayers },
  ]
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
  // split starts_at ISO into date/time
  if (t.value.starts_at) {
    const d = new Date(t.value.starts_at)
    if (!isNaN(d.getTime())) {
      editStartsDate.value = d.toISOString().slice(0,10)
      editStartsTime.value = d.toISOString().slice(11,16)
    }
  } else { editStartsDate.value=''; editStartsTime.value='' }
  editMin.value = t.value.min_players ?? 6
  editMax.value = t.value.max_players ?? ''
  editPoints.value = t.value.target_points ?? 5
  editTime.value = t.value.time_control ?? 'normal'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const tid = props.id || String(route.params.id)
    t.value = await apiFetch<TournamentDetail>(`/api/admin/tournaments/${tid}`)
    if (t.value?.definition) parseDefinition(t.value.definition)
    parseTournamentMeta()
    editing.value = t.value?.state === 'draft' && route.query.edit === '1'
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load'
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function remove() {
  if (!confirm('Delete this draft?')) return
  try {
    const tid = props.id || String(route.params.id)
    await apiFetch(`/api/admin/tournaments/${tid}`, { method: 'DELETE' })
    router.push('/tournaments')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Delete failed'
  }
}

function addStage() { stages.value.push({ id: `stage_${stages.value.length + 1}`, name: 'New Stage', mode: 'knockout' }) }
function removeStage(idx: number) { stages.value.splice(idx, 1) }
function addPodium() { const ref = stages.value[0]?.id || 'main_round'; podium.value.push(`${ref}.placements[0]`) }

async function save() {
  if (t.value?.state !== 'draft') return
  saving.value = true
  error.value = ''
  try {
    const defObj = yaml.load(editYaml.value) as unknown as Record<string, unknown>
    const payloadDef = stages.value.length ? { stages: stages.value.map(s => ({ id: s.id, name: s.name, mode: s.mode })), podium: podium.value } : defObj
    const tid = props.id || String(route.params.id)
    const starts_at = editStartsDate.value ? `${editStartsDate.value}T${editStartsTime.value || '00:00'}` : null
    await apiFetch(`/api/admin/tournaments/${tid}`, {
      method: 'PUT',
      body: JSON.stringify({ name: editName.value, definition: payloadDef, starts_at, min_players: Number(editMin.value), max_players: editMax.value === '' ? null : Number(editMax.value), target_points: Number(editPoints.value), time_control: editTime.value }),
    })
    editing.value = false
    await load()
  } catch (e: unknown) {
    error.value = formatApiError(e)
  } finally { saving.value = false }
}

async function publish() {
  try { const tid = props.id || String(route.params.id); await apiFetch(`/api/admin/tournaments/${tid}/publish`, { method: 'POST' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
async function publishAndManagePlayers() {
  await publish()
  if (t.value?.state === 'open') router.push(`/tournaments/${t.value.id}/attendees`)
}
async function revertToDraft() {
  if (!confirm('All current attendees will be removed. Revert to draft?')) return
  try { const tid = props.id || String(route.params.id); await apiFetch(`/api/admin/tournaments/${tid}/draft`, { method: 'POST' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
async function start() {
  if (!confirm('People will not be able to join after start. Start tournament?')) return
  try { const tid = props.id || String(route.params.id); await apiFetch(`/api/admin/tournaments/${tid}/start`, { method: 'POST' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}

function formatDate(s: string | null) {
  if (!s) return 'Not scheduled yet'
  try {
    return new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return s }
}

function playerRange(min: number, max: number | null) {
  return max === null ? `${min}+ players` : `${min}–${max} players`
}

function participantMessage(count: number) {
  if (count === 1) return '1 player has already registered'
  return `${count} players have already registered`
}
</script>

<template>
  <div class="mx-auto w-full max-w-3xl">
    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else-if="t" class="space-y-4">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" />
      <header class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <RouterLink to="/tournaments" class="mb-2 inline-block text-sm text-zinc-600 hover:text-black hover:underline">← All tournaments</RouterLink>
          <div class="flex flex-wrap items-center gap-2">
            <h1 class="text-2xl font-bold text-black">{{ t.name }}</h1>
            <TournamentStatusBadge :state="t.state" />
          </div>
          <p class="mt-1 flex flex-wrap items-center gap-1 text-sm text-zinc-500">
            <span>Created by</span>
            <UserQuickView :user-id="t.creator_id" :username="t.creator || 'Unknown user'" />
            <span>· Tournament #{{ t.id }}</span>
          </p>
        </div>
      </header>

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <p class="mb-4 text-sm font-medium text-zinc-700">{{ participantMessage(t.participant_count) }}</p>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-zinc-50 p-3 text-sm sm:grid-cols-4">
          <TournamentMetaItem label="Starts" :value="formatDate(t.starts_at)" />
          <TournamentMetaItem label="Players" :value="playerRange(t.min_players, t.max_players)" />
          <TournamentMetaItem label="Match" :value="`Race to ${t.target_points}`" />
          <TournamentMetaItem label="Time control" :value="t.time_control" />
        </dl>
        <div v-if="t.participants?.length" class="mt-4 border-t border-zinc-100 pt-4">
          <div class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Registered players</div>
          <div class="flex flex-wrap gap-2">
            <span v-for="participant in t.participants" :key="participant.id" class="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-700">
              <UserQuickView :user-id="participant.user_id" :username="participant.username || participant.name" />
            </span>
          </div>
        </div>
      </section>

      <section class="rounded-xl border border-zinc-200 bg-white p-5">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div><h2 class="font-semibold text-black">Tournament readiness</h2><p class="mt-1 text-sm text-zinc-500">Complete these steps before the first round starts.</p></div>
          <span :class="['rounded-full px-2.5 py-1 text-xs font-semibold', readinessItems.every(item => item.done) ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800']">{{ readinessItems.filter(item => item.done).length }}/{{ readinessItems.length }} complete</span>
        </div>
        <ul class="grid gap-2 sm:grid-cols-2">
          <li v-for="item in readinessItems" :key="item.label" class="flex items-center gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-sm">
            <span :class="['flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold', item.done ? 'bg-emerald-600 text-white' : 'border border-zinc-300 bg-white text-zinc-400']">{{ item.done ? '✓' : '·' }}</span>
            <span :class="item.done ? 'text-zinc-800' : 'text-zinc-500'">{{ item.label }}</span>
          </li>
        </ul>
      </section>

      <!-- Visual editor for stages/podium (draft only) -->
      <div v-if="t.state==='draft'" class="rounded-lg border border-zinc-200 bg-zinc-50 p-4">
        <div class="mb-3 flex items-center justify-between">
          <div><h3 class="text-sm font-semibold text-black">Draft settings</h3><p class="text-xs text-zinc-500">Review the player-facing rules before publishing.</p></div>
          <button @click="editing = !editing" :class="['rounded px-3 py-1 text-xs font-medium', editing ? 'bg-zinc-900 text-white' : 'bg-white border border-zinc-300 text-black']">{{ editing ? 'Close editor' : 'Edit details' }}</button>
        </div>
        <div v-if="editing" class="mb-4 rounded bg-white border border-zinc-200 p-3 space-y-3">
          <label class="block"><span class="mb-1 block text-xs font-medium text-black">Name</span><input v-model="editName" class="w-full rounded border border-zinc-300 px-2 py-1 text-sm text-black" /></label>
          <TournamentMetaFields :starts-date="editStartsDate" :starts-time="editStartsTime" :time-control="editTime" :min-players="Number(editMin)" :max-players="editMax" :target-points="Number(editPoints)" @update:starts-date="editStartsDate=$event" @update:starts-time="editStartsTime=$event" @update:time-control="editTime=$event" @update:min-players="editMin=$event" @update:max-players="editMax=$event" @update:target-points="editPoints=$event" />
        </div>
        <h4 class="mb-2 text-xs font-semibold text-zinc-700">Tournament structure</h4>

        <div v-if="!editing" class="space-y-2">
          <div v-for="s in stages" :key="s.id" class="flex items-center gap-2 rounded bg-white border border-zinc-200 px-3 py-2 text-sm">
            <span class="inline-flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs text-white">{{ s.mode === 'knockout' ? '🏆' : s.mode === 'division' ? '⊞' : '▦' }}</span>
            <span class="font-medium text-black">{{ s.name }}</span><span class="text-xs capitalize text-zinc-500">{{ s.mode === 'division' ? 'League' : s.mode }}</span>
          </div>
          <div class="flex flex-wrap gap-1 pt-2">
            <span v-for="(p, i) in podium" :key="i" :title="p" class="rounded-full bg-white border border-zinc-200 px-2 py-1 text-xs">{{ i===0 ? '🥇' : i===1 ? '🥈' : '🥉' }} {{ p.split('.')[0] }} {{ ['1st','2nd','3rd','4th'][Number(p.match(/\d+/)?.[0] ?? '0')] || p }}</span>
          </div>
        </div>

        <div v-else class="space-y-3">
          <details class="rounded border border-zinc-200 bg-white p-3">
            <summary class="cursor-pointer text-sm font-medium text-black">Advanced structure settings</summary>
            <p class="mt-1 text-xs text-zinc-500">Stage IDs, podium mapping and YAML are intended for custom tournament formats.</p>
            <div class="mt-3 space-y-3">
              <div v-for="(s, idx) in stages" :key="idx" class="grid grid-cols-12 gap-2 rounded border border-zinc-200 p-2">
                <input v-model="s.id" placeholder="Internal ID" class="col-span-3 rounded border border-zinc-300 px-2 py-1 text-xs text-black" /><input v-model="s.name" placeholder="Name" class="col-span-4 rounded border border-zinc-300 px-2 py-1 text-xs text-black" /><select v-model="s.mode" class="col-span-3 rounded border border-zinc-300 px-2 py-1 text-xs text-black"><option value="knockout">Knockout</option><option value="division">League</option><option value="groups">Groups</option></select><button @click="removeStage(idx)" class="col-span-2 rounded bg-red-50 px-2 py-1 text-xs text-red-600">Remove</button>
              </div>
              <button @click="addStage" class="rounded border border-dashed border-zinc-300 px-3 py-1 text-xs">+ Add stage</button>
              <div v-for="(p, i) in podium" :key="i" class="flex items-center gap-2"><span class="w-12 text-xs font-medium">Place {{ i + 1 }}</span><select :value="p.split('.')[0]" @change="podium[i] = `${($event.target as HTMLSelectElement).value}.placements[${p.match(/\d+/)?.[0] ?? '0'}]`" class="rounded border border-zinc-300 px-2 py-1 text-xs"><option v-for="s in stages" :key="s.id" :value="s.id">{{ s.name }}</option></select><button @click="podium.splice(i,1)" class="text-xs text-red-600">Remove</button></div>
              <button @click="addPodium" class="rounded border border-zinc-300 px-2 py-1 text-xs">+ Add podium place</button>
              <details><summary class="cursor-pointer text-xs text-zinc-600">Edit raw YAML</summary><textarea v-model="editYaml" rows="8" class="mt-2 w-full rounded border border-zinc-300 p-2 font-mono text-xs text-black"></textarea></details>
            </div>
          </details>

          <button @click="save" :disabled="saving" class="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">{{ saving ? 'Saving…' : 'Save draft' }}</button>
        </div>
      </div>

      <div v-else class="rounded bg-zinc-50 border border-zinc-200 p-3 font-mono text-xs whitespace-pre-wrap text-black">{{ t.definition }}</div>

      <div class="flex flex-wrap gap-2">
        <RouterLink to="/tournaments" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black hover:bg-zinc-50">Back</RouterLink>
        <template v-if="t.state==='draft'">
          <button @click="publishAndManagePlayers" class="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">Publish and add players</button>
          <button @click="remove" class="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700">Delete draft</button>
        </template>
        <template v-if="t.state==='open'">
          <button @click="revertToDraft" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black hover:bg-zinc-50">Revert to draft</button>
          <RouterLink :to="`/tournaments/${t.id}/attendees`" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-black">Manage players</RouterLink>
          <button @click="start" :disabled="t.participant_count < t.min_players" class="rounded bg-amber-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-40">{{ t.participant_count < t.min_players ? `Need ${t.min_players - t.participant_count} more players` : 'Start tournament' }}</button>
        </template>
        <template v-if="['active','finished'].includes(t.state)">
          <RouterLink :to="`/tournaments/${t.id}/attendees`" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black">Attendees</RouterLink>
          <RouterLink :to="`/tournaments/${t.id}/progress`" class="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-black">{{ t.state === 'finished' ? 'Results' : 'Progress' }}</RouterLink>
        </template>
      </div>
    </div>
  </div>
</template>
