<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import AppAlert from '@/components/AppAlert.vue'
import * as yaml from 'js-yaml'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
interface TournamentDetail {
  id: number
  name: string
  state: string
  creator: string | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
  definition: string
  participants: string[]
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

const yamlPreview = computed(() => {
  return yaml.dump({ stages: stages.value.map(s => ({ id: s.id, name: s.name, mode: s.mode })), podium: podium.value })
})

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
async function revertToDraft() {
  if (!confirm('All current attendees will be removed. Revert to draft?')) return
  try { const tid = props.id || String(route.params.id); await apiFetch(`/api/admin/tournaments/${tid}/draft`, { method: 'POST' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
async function start() {
  if (!confirm('People will not be able to join after start. Start tournament?')) return
  try { const tid = props.id || String(route.params.id); await apiFetch(`/api/admin/tournaments/${tid}/start`, { method: 'POST' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}

function badgeClass(s: string) {
  if (s === 'draft') return 'bg-zinc-100 text-zinc-700 border-zinc-200'
  if (s === 'open') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (s === 'active') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (s === 'finished') return 'bg-zinc-900 text-white border-zinc-900'
  return 'bg-zinc-100 text-zinc-700 border-zinc-200'
}
</script>

<template>
  <div class="mx-auto w-full max-w-3xl">
    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else-if="t" class="space-y-4">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" />
      <div class="flex items-start justify-between gap-3">
        <h1 class="text-2xl font-bold text-black">{{ t.name }} <span :class="['ml-2 rounded-full border px-2 py-0.5 text-2xl ', badgeClass(t.state)]">{{ t.state }}</span></h1>
        <span class="text-xs text-zinc-500">#{{ t.id }}</span>
      </div>

      <div class="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-black">
        <div class="grid grid-cols-2 gap-2 text-xs text-zinc-600">
          <div><span class="font-medium text-zinc-700">Creator:</span> {{ t.creator || '—' }}</div>
          <div><span class="font-medium text-zinc-700">Attendees:</span> {{ t.participant_count }}</div>
          <div><span class="font-medium text-zinc-700">Starts:</span> {{ t.starts_at || '—' }}</div>
          <div><span class="font-medium text-zinc-700">Players:</span> {{ t.min_players }}–{{ t.max_players ?? '∞' }} • {{ t.target_points }} pts • {{ t.time_control }}</div>
        </div>
        <div v-if="t.participants?.length" class="mt-3 text-xs"><span class="font-medium text-zinc-700">Attendees:</span> {{ t.participants.join(', ') }}</div>
      </div>

      <!-- Visual editor for stages/podium (draft only) -->
      <div v-if="t.state==='draft'" class="rounded-lg border border-zinc-200 bg-zinc-50 p-4">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-black">Edit Tournament</h3>
          <button @click="editing = !editing" :class="['rounded px-3 py-1 text-xs font-medium', editing ? 'bg-zinc-900 text-white' : 'bg-white border border-zinc-300 text-black']">{{ editing ? 'Preview' : 'Edit' }}</button>
        </div>
        <div v-if="editing" class="mb-4 rounded bg-white border border-zinc-200 p-3 space-y-3">
          <label class="block"><span class="mb-1 block text-xs font-medium text-black">Name</span><input v-model="editName" class="w-full rounded border border-zinc-300 px-2 py-1 text-sm text-black" /></label>
          <TournamentMetaFields :starts-date="editStartsDate" :starts-time="editStartsTime" :time-control="editTime" :min-players="Number(editMin)" :max-players="editMax" :target-points="Number(editPoints)" @update:starts-date="editStartsDate=$event" @update:starts-time="editStartsTime=$event" @update:time-control="editTime=$event" @update:min-players="editMin=$event" @update:max-players="editMax=$event" @update:target-points="editPoints=$event" />
        </div>
        <h4 class="mb-2 text-xs font-semibold text-zinc-700">Stages & Podium</h4>

        <div v-if="!editing" class="space-y-2">
          <div v-for="s in stages" :key="s.id" class="flex items-center gap-2 rounded bg-white border border-zinc-200 px-3 py-2 text-sm">
            <span class="inline-flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs text-white">{{ s.mode === 'knockout' ? '🏆' : s.mode === 'division' ? '⊞' : '▦' }}</span>
            <span class="font-medium text-black">{{ s.name }}</span><span class="text-xs text-zinc-500">({{ s.id }} • {{ s.mode }})</span>
          </div>
          <div class="flex flex-wrap gap-1 pt-2">
            <span v-for="(p, i) in podium" :key="i" :title="p" class="rounded-full bg-white border border-zinc-200 px-2 py-1 text-xs">{{ i===0 ? '🥇' : i===1 ? '🥈' : '🥉' }} {{ p.split('.')[0] }} {{ ['1st','2nd','3rd','4th'][Number(p.match(/\d+/)?.[0] ?? '0')] || p }}</span>
          </div>
          <div class="pt-2 text-xs text-zinc-500">YAML preview:</div>
          <pre class="rounded bg-white border border-zinc-200 p-2 text-xs font-mono whitespace-pre-wrap text-black">{{ yamlPreview }}</pre>
        </div>

        <div v-else class="space-y-3">
          <div v-for="(s, idx) in stages" :key="idx" class="grid grid-cols-12 gap-2 rounded bg-white border border-zinc-200 p-2">
            <input v-model="s.id" placeholder="id" class="col-span-3 rounded border border-zinc-300 px-2 py-1 text-xs text-black" />
            <input v-model="s.name" placeholder="Name" class="col-span-4 rounded border border-zinc-300 px-2 py-1 text-xs text-black" />
            <select v-model="s.mode" class="col-span-3 rounded border border-zinc-300 px-2 py-1 text-xs text-black"><option value="knockout">knockout</option><option value="division">division</option><option value="groups">groups</option></select>
            <button @click="removeStage(idx)" class="col-span-2 rounded bg-red-50 px-2 py-1 text-xs text-red-600 hover:bg-red-100">Remove</button>
          </div>
          <button @click="addStage" class="rounded border border-dashed border-zinc-300 bg-white px-3 py-1 text-xs text-black hover:bg-zinc-50">+ Add stage</button>

          <div class="space-y-1">
            <div class="text-xs font-medium text-black">Podium — final ranking (1st, 2nd, 3rd…) taken from stage placements</div>
            <p class="text-xs text-zinc-500">e.g. <span class="font-mono">main_round.placements[0]</span> = Winner of Main Round (1st place). <span class="font-mono">[1]</span> = 2nd place, <span class="font-mono">[2]</span> = 3rd.</p>
            <div v-for="(p, i) in podium" :key="i" class="flex items-center gap-2">
              <span class="w-10 text-xs font-medium text-zinc-700">{{ i===0 ? '🥇 1st' : i===1 ? '🥈 2nd' : `🥉 ${i+1}th` }}</span>
              <select :value="p.split('.')[0]" @change="podium[i] = `${($event.target as HTMLSelectElement).value}.placements[${p.match(/\d+/)?.[0] ?? '0'}]`" class="rounded border border-zinc-300 px-2 py-1 text-xs text-black">
                <option v-for="s in stages" :key="s.id" :value="s.id">{{ s.name }} ({{ s.id }})</option>
              </select>
              <select :value="p.match(/\d+/)?.[0] ?? '0'" @change="podium[i] = `${p.split('.')[0]}.placements[${($event.target as HTMLSelectElement).value}]`" class="rounded border border-zinc-300 px-2 py-1 text-xs text-black">
                <option value="0">1st place</option><option value="1">2nd place</option><option value="2">3rd place</option><option value="3">4th place</option>
              </select>
              <span class="font-mono text-xs text-zinc-500 hidden sm:inline">{{ p }}</span>
              <button @click="podium.splice(i,1)" class="rounded px-2 py-1 text-xs text-red-600">×</button>
            </div>
            <button @click="addPodium" class="rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-black">+ Add podium entry</button>
          </div>

          <details class="rounded border border-zinc-200 bg-white p-2"><summary class="cursor-pointer text-xs font-medium text-black">Advanced: edit raw YAML</summary><textarea v-model="editYaml" rows="8" class="mt-2 w-full rounded border border-zinc-300 p-2 font-mono text-xs text-black"></textarea></details>

          <button @click="save" :disabled="saving" class="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">{{ saving ? 'Saving…' : 'Save draft' }}</button>
        </div>
      </div>

      <div v-else class="rounded bg-zinc-50 border border-zinc-200 p-3 font-mono text-xs whitespace-pre-wrap text-black">{{ t.definition }}</div>

      <div class="flex flex-wrap gap-2">
        <RouterLink to="/tournaments" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black hover:bg-zinc-50">Back</RouterLink>
        <template v-if="t.state==='draft'">
          <button @click="publish" class="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">Publish</button>
          <button @click="remove" class="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700">Delete draft</button>
        </template>
        <template v-if="t.state==='open'">
          <button @click="revertToDraft" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black hover:bg-zinc-50">Revert to draft</button>
          <RouterLink :to="`/tournaments/${t.id}/attendees`" class="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-black">Manage attendees</RouterLink>
          <button @click="start" class="rounded bg-amber-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-600">Start</button>
        </template>
        <template v-if="['active','finished'].includes(t.state)">
          <RouterLink :to="`/tournaments/${t.id}/attendees`" class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm text-black">Attendees</RouterLink>
          <RouterLink :to="`/tournaments/${t.id}/progress`" class="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-black">{{ t.state === 'finished' ? 'Results' : 'Progress' }}</RouterLink>
        </template>
      </div>
    </div>
  </div>
</template>
