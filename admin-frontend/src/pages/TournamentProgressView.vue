<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import AppAlert from '@/components/AppAlert.vue'

const route = useRoute()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const data = ref<any>(null)
const savingId = ref<number | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try { data.value = await apiFetch<any>(`/api/admin/tournaments/${id}/progress`) } catch (e: unknown) { error.value = formatApiError(e) } finally { loading.value = false }
}
onMounted(load)

async function submit(fixture: any, score1: string, score2: string) {
  savingId.value = fixture.id
  error.value = ''
  try {
    await apiFetch(`/api/admin/tournaments/${id}/progress`, { method: 'POST', body: JSON.stringify({ fixture_id: fixture.id, score1, score2 }) })
    await load()
  } catch (e: unknown) { error.value = formatApiError(e) } finally { savingId.value = null }
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl">
    <h1 class="mb-1 text-2xl font-bold text-black">Tournament Progress</h1>
    <p v-if="data?.tournament" class="mb-4 text-sm text-zinc-600">{{ data.tournament.name }} • <span :class="['rounded-full border px-2 py-0.5 text-xs', data.tournament.state==='finished' ? 'bg-zinc-900 text-white' : 'bg-amber-50 text-amber-700']">{{ data.tournament.state }}</span></p>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <AppAlert v-if="error" type="error" :message="error" dismissible @close="error=''" class="mb-3" />
    <div v-else-if="data" class="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div class="lg:col-span-1">
        <div class="rounded-lg border border-zinc-200 bg-white p-4 text-sm">
          <div class="font-semibold text-black">{{ data.tournament.name }}</div>
          <div class="text-xs text-zinc-500">#{{ data.tournament.id }} • {{ data.tournament.participant_count }} attendees</div>
          <div v-if="data.is_finished && data.podium?.length" class="mt-3">
            <div class="text-xs font-semibold text-black">Podium</div>
            <div v-for="(p, idx) in data.podium" :key="p.id" class="text-xs"><span :class="{'text-amber-600': idx===0, 'text-zinc-500': idx===1, 'text-amber-800': idx===2}">{{ idx===0 ? '🥇' : idx===1 ? '🥈' : '🥉' }} {{ p.name }}</span></div>
          </div>
        </div>
      </div>
      <div class="lg:col-span-2 space-y-4">
        <div v-for="(stageInfo, stageId) in data.stages" :key="String(stageId)" class="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 class="mb-2 text-sm font-semibold text-black">{{ String(stageId) }}</h3>
          <div v-for="(level, lidx) in (stageInfo as any).levels" :key="lidx" class="mb-3 rounded border border-zinc-200 p-3">
            <div class="mb-2 text-xs font-medium text-zinc-700">Level {{ lidx }}<span v-if="level.name">: {{ level.name }}</span></div>
            <div v-for="f in level.fixtures" :key="f.id" class="mb-2 rounded bg-zinc-50 p-2">
              <div class="flex items-center justify-between gap-2 text-sm">
                <span class="font-medium text-black">{{ f.player1?.name || '—' }}</span>
                <div class="flex items-center gap-1">
                  <input v-if="f.editable && !f.has_confirmed" :id="`s1-${f.id}`" :value="f.score1 ?? ''" placeholder="—" class="w-12 rounded border border-zinc-300 bg-white px-1 py-1 text-center text-sm text-black" />
                  <span v-else class="w-12 text-center text-black">{{ f.score1 ?? '—' }}</span>
                  <span class="text-zinc-400">:</span>
                  <input v-if="f.editable && !f.has_confirmed" :id="`s2-${f.id}`" :value="f.score2 ?? ''" placeholder="—" class="w-12 rounded border border-zinc-300 bg-white px-1 py-1 text-center text-sm text-black" />
                  <span v-else class="w-12 text-center text-black">{{ f.score2 ?? '—' }}</span>
                </div>
                <span class="font-medium text-black">{{ f.player2?.name || '—' }}</span>
              </div>
              <div class="mt-2 flex items-center justify-between text-xs">
                <span class="text-zinc-500">Confirmations: {{ f.confirmations }} / {{ f.required_confirmations }}<span v-if="f.has_confirmed" class="ml-2 text-emerald-600">✓ You confirmed</span></span>
                <button v-if="f.editable && !f.has_confirmed" @click="submit(f, (document.getElementById(`s1-${f.id}`) as HTMLInputElement)?.value || '', (document.getElementById(`s2-${f.id}`) as HTMLInputElement)?.value || '')" :disabled="savingId===f.id" class="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">{{ f.score1==null ? 'Submit' : 'Confirm' }}</button>
              </div>
            </div>
          </div>
        </div>
        <RouterLink :to="`/tournaments/${id}`" class="text-sm text-zinc-600 hover:underline">← Back to tournament</RouterLink>
      </div>
    </div>
  </div>
</template>
