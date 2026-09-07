<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import AppAlert from '@/components/AppAlert.vue'
import StartTournamentDialog from '@/components/tournament/StartTournamentDialog.vue'
import TournamentProgress from '@/components/tournament/TournamentProgress.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import { useTournamentWorkspace } from '@/composables/useTournamentWorkspace'
import { useI18n } from '@/i18n'
import { apiFetch, formatApiError } from '@/services/api'

interface DrawParticipant {
  id: number
  name: string
  user_id: number | null
  username: string | null
  position: number
}

interface TournamentDraw {
  tournament_id: number
  lifecycle_state: string
  participant_count: number
  min_players: number
  generated_at: string | null
  confirmed_at: string | null
  has_draw: boolean
  participants: DrawParticipant[]
}

const route = useRoute()
const router = useRouter()
const workspace = useTournamentWorkspace()
const { t } = useI18n()
const draw = ref<TournamentDraw | null>(null)
const order = ref<DrawParticipant[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const showStartDialog = ref(false)
const id = computed(() => String(route.params.id))
const tournamentName = computed(() => workspace?.tournament.value?.name ?? t('tournamentDraw.tournament'))
const lifecycle = computed(() => draw.value?.lifecycle_state ?? '')
const state = computed(() => {
  if (['active', 'finished', 'results_confirmed', 'draft'].includes(lifecycle.value)) {
    return lifecycle.value === 'results_confirmed' ? 'finished' : lifecycle.value
  }
  return 'open'
})
const enoughPlayers = computed(() => Boolean(draw.value && draw.value.participant_count >= draw.value.min_players))
const editableDraw = computed(() => lifecycle.value === 'draw_ready')
const showOrder = computed(() => Boolean(draw.value?.has_draw || ['ready_to_start', 'active', 'finished', 'results_confirmed'].includes(lifecycle.value)))
const orderDirty = computed(() => order.value.some((participant, index) => participant.id !== draw.value?.participants[index]?.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    draw.value = await apiFetch<TournamentDraw>(`/api/admin/tournaments/${id.value}/draw`)
    order.value = draw.value.participants.map(participant => ({ ...participant }))
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

async function run(path: string, body?: Record<string, unknown>) {
  if (busy.value) return false
  busy.value = true
  error.value = ''
  try {
    await apiFetch(path, {
      method: 'POST',
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    await load()
    await workspace?.refresh()
    return true
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
    return false
  } finally {
    busy.value = false
  }
}

async function closeRegistration() {
  await run(`/api/admin/tournaments/${id.value}/registration/close`)
}

async function reopenRegistration() {
  if (!confirm(t('tournamentDraw.reopenConfirm'))) return
  await run(`/api/admin/tournaments/${id.value}/registration/reopen`)
}

async function generateDraw() {
  await run(`/api/admin/tournaments/${id.value}/draw`)
}

async function saveOrder() {
  return run(`/api/admin/tournaments/${id.value}/draw`, {
    participant_ids: order.value.map(participant => participant.id),
  })
}

async function confirmDraw() {
  if (orderDirty.value && !await saveOrder()) return
  await run(`/api/admin/tournaments/${id.value}/draw/confirm`)
}

function move(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= order.value.length) return
  const current = order.value[index]
  const replacement = order.value[target]
  if (!current || !replacement) return
  order.value[index] = replacement
  order.value[target] = current
}

async function startTournament() {
  const started = await run(`/api/admin/tournaments/${id.value}/start`)
  if (!started) return
  showStartDialog.value = false
  await router.push({ name: 'tournament-live', params: { id: id.value } })
}

onMounted(load)
</script>

<template>
  <div class="draw-page">
    <header class="draw-page__heading">
      <div><h2>{{ t('tournamentDraw.title') }}</h2><p>{{ t('tournamentDraw.subtitle') }}</p></div>
      <span v-if="draw" class="draw-page__count"><i class="bi bi-people" aria-hidden="true"></i>{{ t('tournamentDraw.playerCount', { count: draw.participant_count }) }}</span>
    </header>

    <div v-if="loading" class="draw-page__loading" role="status">{{ t('common.loading') }}</div>
    <template v-else-if="draw">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error = ''" />
      <TournamentProgress :state="state" :lifecycle-state="lifecycle" :participant-count="draw.participant_count" :min-players="draw.min_players" />

      <section class="draw-command">
        <div class="draw-command__copy">
          <p>{{ t('tournamentActions.nextStep') }}</p>
          <template v-if="lifecycle === 'registration_open'">
            <h3>{{ t('tournamentDraw.closeRegistration') }}</h3>
            <span>{{ t(enoughPlayers ? 'tournamentDraw.closeRegistrationHint' : 'tournamentDraw.morePlayersHint', { count: Math.max(0, draw.min_players - draw.participant_count) }) }}</span>
          </template>
          <template v-else-if="lifecycle === 'registration_closed'">
            <h3>{{ t('tournamentDraw.generateTitle') }}</h3><span>{{ t('tournamentDraw.generateHint') }}</span>
          </template>
          <template v-else-if="lifecycle === 'draw_ready'">
            <h3>{{ t('tournamentDraw.reviewTitle') }}</h3><span>{{ t('tournamentDraw.reviewHint') }}</span>
          </template>
          <template v-else-if="lifecycle === 'ready_to_start'">
            <h3>{{ t('tournamentDraw.readyTitle') }}</h3><span>{{ t('tournamentDraw.readyHint') }}</span>
          </template>
          <template v-else>
            <h3>{{ t('tournamentDraw.lockedTitle') }}</h3><span>{{ t('tournamentDraw.lockedHint') }}</span>
          </template>
        </div>
        <div class="draw-command__actions">
          <Button v-if="lifecycle === 'registration_open'" :label="t('tournamentDraw.closeAction')" icon="bi bi-lock" severity="success" :loading="busy" :disabled="!enoughPlayers" @click="closeRegistration" />
          <template v-else-if="lifecycle === 'registration_closed'">
            <Button :label="t('tournamentDraw.generateAction')" icon="bi bi-shuffle" severity="success" :loading="busy" @click="generateDraw" />
            <Button :label="t('tournamentDraw.reopenAction')" severity="secondary" outlined :disabled="busy" @click="reopenRegistration" />
          </template>
          <template v-else-if="lifecycle === 'draw_ready'">
            <Button :label="t('tournamentDraw.confirmAction')" icon="bi bi-check2-circle" severity="success" :loading="busy" @click="confirmDraw" />
            <Button :label="t('tournamentDraw.regenerateAction')" icon="bi bi-shuffle" severity="secondary" outlined :disabled="busy" @click="generateDraw" />
            <Button :label="t('tournamentDraw.reopenAction')" severity="secondary" text :disabled="busy" @click="reopenRegistration" />
          </template>
          <template v-else-if="lifecycle === 'ready_to_start'">
            <Button :label="t('tournamentActions.start')" icon="bi bi-play" severity="success" @click="showStartDialog = true" />
            <Button :label="t('tournamentDraw.reopenAction')" severity="secondary" outlined :disabled="busy" @click="reopenRegistration" />
          </template>
        </div>
      </section>

      <section class="draw-preview">
        <header>
          <div><h3>{{ t(showOrder ? 'tournamentDraw.previewTitle' : 'tournamentDraw.registeredTitle') }}</h3><p>{{ t(showOrder ? 'tournamentDraw.previewHint' : 'tournamentDraw.registeredHint') }}</p></div>
          <Button v-if="editableDraw" :label="t('tournamentDraw.saveOrder')" size="small" severity="secondary" outlined :loading="busy" @click="saveOrder" />
        </header>
        <ol>
          <li v-for="(participant, index) in order" :key="participant.id">
            <span class="draw-preview__seed">{{ index + 1 }}</span>
            <UserQuickView :user-id="participant.user_id" :username="participant.username || participant.name" />
            <div v-if="editableDraw" class="draw-preview__move">
              <button type="button" :aria-label="t('tournamentDraw.moveUp', { name: participant.name })" :disabled="index === 0" @click="move(index, -1)"><i class="bi bi-chevron-up" aria-hidden="true"></i></button>
              <button type="button" :aria-label="t('tournamentDraw.moveDown', { name: participant.name })" :disabled="index === order.length - 1" @click="move(index, 1)"><i class="bi bi-chevron-down" aria-hidden="true"></i></button>
            </div>
            <i v-else-if="showOrder" class="bi bi-lock draw-preview__locked" aria-hidden="true"></i>
          </li>
        </ol>
      </section>
    </template>
    <AppAlert v-else-if="error" type="error" :message="error" />

    <StartTournamentDialog
      v-if="showStartDialog && draw"
      :name="tournamentName"
      :participant-count="draw.participant_count"
      :busy="busy"
      :error="error"
      @confirm="startTournament"
      @cancel="showStartDialog = false"
    />
  </div>
</template>

<style scoped>
.draw-page { display: grid; gap: 18px; width: 100%; max-width: 980px; margin: 0 auto; }
.draw-page__heading { display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid #263653; }
.draw-page__heading h2 { color: #eef3ff; font-size: 21px; font-weight: 700; }
.draw-page__heading p { margin-top: 4px; color: #aab8d4; font-size: 12px; }
.draw-page__count { display: inline-flex; align-items: center; gap: 7px; color: #b6c8df; font-size: 12px; }
.draw-page__loading { min-height: 260px; padding-top: 100px; text-align: center; color: #aab8d4; }
.draw-command { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 21px; border: 1px solid #295273; border-radius: 14px; background: linear-gradient(135deg, #132a42, #111b30); }
.draw-command__copy > p { margin: 0 0 6px; color: #79d3ff; font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
.draw-command h3 { margin: 0; color: #f2f6ff; font-size: 18px; font-weight: 680; }
.draw-command__copy > span { display: block; margin-top: 6px; color: #afc1d9; font-size: 12px; line-height: 1.5; }
.draw-command__actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.draw-preview { padding: 20px; border: 1px solid #293b59; border-radius: 14px; background: #111b30; }
.draw-preview > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 15px; }
.draw-preview h3 { margin: 0; color: #eff4ff; font-size: 15px; font-weight: 680; }
.draw-preview header p { margin: 4px 0 0; color: #9eafc7; font-size: 11px; }
.draw-preview ol { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin: 0; padding: 0; list-style: none; }
.draw-preview li { display: flex; align-items: center; min-width: 0; gap: 10px; padding: 11px; border: 1px solid #30415e; border-radius: 10px; background: #162139; color: #e7effd; font-size: 13px; }
.draw-preview__seed { display: grid; flex: 0 0 28px; height: 28px; place-items: center; border-radius: 8px; background: #223b5f; color: #a8d6ff; font-weight: 700; }
.draw-preview__move { display: flex; margin-inline-start: auto; }
.draw-preview__move button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 6px; background: transparent; color: #a9bfdc; }
.draw-preview__move button:not(:disabled):hover { background: #273b59; color: white; }
.draw-preview__move button:disabled { opacity: .25; }
.draw-preview__locked { margin-inline-start: auto; color: #6e83a1; }
@media (max-width: 700px) {
  .draw-command { align-items: stretch; flex-direction: column; }
  .draw-command__actions { justify-content: flex-start; }
  .draw-preview ol { grid-template-columns: 1fr; }
}
</style>
