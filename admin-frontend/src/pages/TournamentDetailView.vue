<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import TournamentMetaFields from '@/components/TournamentMetaFields.vue'
import AppAlert from '@/components/AppAlert.vue'
import TournamentMetaItem from '@/components/TournamentMetaItem.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import { timeControlLabel } from '@/utils/adminLabels'
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
  doubling_enabled: boolean
  entry_fee: string
  prize_money: string
  definition: string
  participants: TournamentParticipant[]
  published: boolean
}
const t = ref<TournamentDetail | null>(null)
const editing = ref(false)
const saving = ref(false)
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
const pad = (value: number) => String(value).padStart(2, '0')
const dateInputValue = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const timeInputValue = (date: Date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`
const now = new Date()
const minStartsDate = ref(dateInputValue(now))
const minStartsTime = computed(() => editStartsDate.value === minStartsDate.value ? timeInputValue(new Date()) : undefined)

interface Stage { id: string; name: string; mode: string }
const stageModeOptions = [
  { value: 'knockout', label: 'Knockout' },
  { value: 'division', label: 'League' },
  { value: 'groups', label: 'Groups' },
]
const stages = ref<Stage[]>([])
const podium = ref<string[]>([])

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
  try {
    const tid = props.id || String(route.params.id)
    t.value = await apiFetch<TournamentDetail>(`/api/admin/tournaments/${tid}`)
    if (t.value?.definition) parseDefinition(t.value.definition)
    parseTournamentMeta()
    editing.value = t.value?.state === 'draft' && route.query.edit === '1'
    if (t.value?.state === 'finished') {
      router.replace(`/tournaments/${t.value.id}/progress`)
    }
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
      body: JSON.stringify({ name: editName.value, definition: payloadDef, starts_at, min_players: Number(editMin.value), max_players: editMax.value === '' ? null : Number(editMax.value), target_points: Number(editPoints.value), time_control: editTime.value, doubling_enabled: editDoubling.value, entry_fee: Number(editEntryFee.value), prize_money: Number(editPrizeMoney.value) }),
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

function stageModeLabel(mode: string) {
  if (mode === 'knockout') return 'Knockout bracket'
  if (mode === 'division') return 'League table'
  if (mode === 'groups') return 'Group stage'
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
  if (placement === 0) return `Winner of ${stageName}`
  if (placement === 1) return `Runner-up of ${stageName}`
  if (placement === 2) return `Third place from ${stageName}`
  return `Place ${placement + 1} from ${stageName}`
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
          <TournamentMetaItem label="Time control" :value="timeControlLabel(t.time_control)" />
          <TournamentMetaItem label="Doubling" :value="t.doubling_enabled ? 'Enabled' : 'Disabled'" />
          <TournamentMetaItem label="Entry fee" :value="Number(t.entry_fee || 0).toFixed(2)" />
          <TournamentMetaItem label="Prize" :value="Number(t.prize_money || 0).toFixed(2)" />
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
          <Button :label="editing ? 'Close editor' : 'Edit details'" size="small" :severity="editing ? 'contrast' : 'secondary'" :outlined="!editing" @click="editing = !editing" />
        </div>
        <div v-if="editing" class="mb-4 rounded bg-white border border-zinc-200 p-3 space-y-3">
          <label class="block"><span class="mb-1 block text-xs font-medium text-black">Name</span><InputText v-model="editName" class="w-full" /></label>
          <TournamentMetaFields :starts-date="editStartsDate" :starts-time="editStartsTime" :time-control="editTime" :min-players="Number(editMin)" :max-players="editMax" :target-points="Number(editPoints)" :doubling-enabled="editDoubling" :entry-fee="editEntryFee" :prize-money="editPrizeMoney" :min-starts-date="minStartsDate" :min-starts-time="minStartsTime" @update:starts-date="editStartsDate=$event" @update:starts-time="editStartsTime=$event" @update:time-control="editTime=$event" @update:min-players="editMin=$event" @update:max-players="editMax=$event" @update:target-points="editPoints=$event" @update:doubling-enabled="editDoubling=$event" @update:entry-fee="editEntryFee=$event" @update:prize-money="editPrizeMoney=$event" />
        </div>
        <h4 class="mb-2 text-xs font-semibold text-zinc-700">Tournament structure</h4>

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
            <summary class="cursor-pointer text-sm font-medium text-black">Advanced structure settings</summary>
            <p class="mt-1 text-xs text-zinc-500">Stage IDs, podium mapping and YAML are intended for custom tournament formats.</p>
            <div class="mt-3 space-y-3">
              <div v-for="(s, idx) in stages" :key="idx" class="grid grid-cols-12 gap-2 rounded border border-zinc-200 p-2">
                <InputText v-model="s.id" placeholder="Internal ID" class="col-span-3 text-xs" /><InputText v-model="s.name" placeholder="Name" class="col-span-4 text-xs" /><Select v-model="s.mode" :options="stageModeOptions" option-label="label" option-value="value" class="col-span-3 text-xs" /><Button label="Remove" size="small" severity="danger" text class="col-span-2" @click="removeStage(idx)" />
              </div>
              <Button label="Add stage" size="small" severity="secondary" outlined @click="addStage" />
              <div v-for="(p, i) in podium" :key="i" class="flex items-center gap-2"><span class="w-12 text-xs font-medium">Place {{ i + 1 }}</span><Select :model-value="p.split('.')[0]" :options="stages" option-label="name" option-value="id" class="min-w-40 text-xs" @update:model-value="podium[i] = `${String($event)}.placements[${p.match(/\d+/)?.[0] ?? '0'}]`" /><Button label="Remove" size="small" severity="danger" text @click="podium.splice(i,1)" /></div>
              <Button label="Add podium place" size="small" severity="secondary" outlined @click="addPodium" />
              <details><summary class="cursor-pointer text-xs text-zinc-600">Edit raw YAML</summary><Textarea v-model="editYaml" rows="8" class="mt-2 w-full font-mono text-xs text-black" /></details>
            </div>
          </details>

          <Button :label="saving ? 'Saving...' : 'Save draft'" :loading="saving" size="small" severity="success" @click="save" />
        </div>
      </div>

      <div v-else class="rounded bg-zinc-50 border border-zinc-200 p-3 font-mono text-xs whitespace-pre-wrap text-black">{{ t.definition }}</div>

      <div class="flex flex-wrap gap-2">
        <Button as="router-link" to="/tournaments" label="Back" severity="secondary" outlined />
        <template v-if="t.state==='draft'">
          <Button label="Publish and add players" severity="success" @click="publishAndManagePlayers" />
          <Button label="Delete draft" severity="danger" @click="remove" />
        </template>
        <template v-if="t.state==='open'">
          <Button label="Revert to draft" severity="secondary" outlined @click="revertToDraft" />
          <Button as="router-link" :to="`/tournaments/${t.id}/attendees`" label="Manage players" severity="secondary" outlined />
          <Button :label="t.participant_count < t.min_players ? `Need ${t.min_players - t.participant_count} more players` : 'Start tournament'" :disabled="t.participant_count < t.min_players" severity="warn" @click="start" />
        </template>
        <template v-if="['active','finished'].includes(t.state)">
          <Button as="router-link" :to="`/tournaments/${t.id}/attendees`" label="Attendees" severity="secondary" outlined />
          <Button as="router-link" :to="`/tournaments/${t.id}/progress`" :label="t.state === 'finished' ? 'Results' : 'Progress'" severity="contrast" />
        </template>
      </div>
    </div>
  </div>
</template>
