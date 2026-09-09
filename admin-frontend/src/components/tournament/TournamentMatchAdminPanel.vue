<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Select from 'primevue/select'
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import Textarea from 'primevue/textarea'
import { apiFetch, ApiError, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type {
  MatchAdministration,
  MatchAdminAction,
  MatchPanelSection,
} from '@/types/matchAdministration'
import MatchTimes from './MatchTimes.vue'
import MatchInternalNote from './MatchInternalNote.vue'
import MatchAuditHistory from './MatchAuditHistory.vue'

const props = withDefaults(
  defineProps<{ tournamentId: string; fixtureId: number; section?: MatchPanelSection }>(),
  { section: 'score' },
)
const emit = defineEmits<{ saved: []; busy: [value: boolean] }>()
const { t, locale } = useI18n()
const data = ref<MatchAdministration | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const success = ref('')
const needsRefresh = ref(false)
const action = ref<MatchAdminAction>('score')
const participantId = ref<number | null>(null)
const score1 = ref<number | null>(null)
const score2 = ref<number | null>(null)
const reason = ref('')
const note = ref('')
const returnFee = ref(false)
const reviewing = ref(false)
const path = computed(
  () => `/api/admin/tournaments/${props.tournamentId}/matches/${props.fixtureId}`,
)
const prefix = computed(() => `match-admin-${props.fixtureId}`)
const refundPlayers = computed(
  () => data.value?.players.filter((p) => p.disqualified && Number(p.refundable) > 0) ?? [],
)
const allOptions = computed(() => {
  const actions: MatchAdminAction[] = data.value?.can_rule ? ['score', 'finish', 'advance', 'disqualify'] : []
  if (refundPlayers.value.length) actions.push('refund')
  return actions.map((value) => ({ value, label: t(`matchAdmin.actions.${value}`) }))
})
const options = computed(() =>
  allOptions.value.filter((o) =>
    props.section === 'players' ? !['score', 'finish'].includes(o.value) : ['score', 'finish'].includes(o.value),
  ),
)
const actionIcons = {
  score: 'bi bi-pencil-square',
  finish: 'bi bi-stop-circle',
  advance: 'bi bi-arrow-up-right',
  disqualify: 'bi bi-person-x',
  refund: 'bi bi-wallet2',
}
function syncAction() {
  if (!['score', 'players'].includes(props.section)) return
  if (!options.value.some((o) => o.value === action.value))
    action.value = options.value[0]?.value ?? 'score'
}
watch(
  () => props.section,
  () => {
    reviewing.value = false
    syncAction()
  },
)
const playerOptions = computed(() =>
  action.value === 'refund' ? refundPlayers.value : (data.value?.players ?? []),
)
const selectedPlayer = computed(() => playerOptions.value.find((p) => p.id === participantId.value))
const isScoreAction = computed(() => action.value === 'score' || action.value === 'finish')
const scoreReachesTarget = computed(() =>
  isScoreAction.value && Math.max(score1.value ?? -1, score2.value ?? -1) >= (data.value?.target_points ?? Infinity),
)
const terminalAction = computed(() => action.value !== 'score' || scoreReachesTarget.value)
const refundAmount = computed(() =>
  Number(selectedPlayer.value?.refundable ?? 0).toLocaleString(locale.value),
)
const valid = computed(
  () =>
    !busy.value &&
    !needsRefresh.value &&
    reason.value.trim().length > 0 &&
    options.value.some((o) => o.value === action.value) &&
    (isScoreAction.value
      ? Number.isInteger(score1.value) &&
        Number.isInteger(score2.value) &&
        score1.value! >= 0 &&
        score2.value! >= 0 &&
        score1.value! <= 32767 &&
        score2.value! <= 32767 &&
        (!terminalAction.value || score1.value !== score2.value)
      : !!selectedPlayer.value),
)
const confirmation = computed(() => {
  const name = selectedPlayer.value?.name ?? ''
  if (action.value === 'score')
    return t(scoreReachesTarget.value ? 'matchAdmin.confirmScoreFinal' : 'matchAdmin.confirmScoreInterim', {
      score: `${score1.value} : ${score2.value}`,
      target: data.value?.target_points ?? 0,
    })
  if (action.value === 'finish')
    return t('matchAdmin.confirmFinish', { score: `${score1.value} : ${score2.value}` })
  if (action.value === 'advance') return t('matchAdmin.confirmAdvance', { name })
  if (action.value === 'refund')
    return t('matchAdmin.confirmRefund', { name, amount: refundAmount.value })
  const opponent = data.value?.players.find((p) => p.id !== participantId.value)?.name ?? ''
  return t('matchAdmin.confirmDisqualify', { name, opponent })
})
watch(action, () => {
  participantId.value = null
  returnFee.value = false
  reviewing.value = false
})
watch(participantId, () => {
  returnFee.value = false
  reviewing.value = false
})
watch(busy, (value) => emit('busy', value), { flush: 'sync' })

async function load(initial = false) {
  if (busy.value) return
  loading.value = true
  error.value = ''
  reviewing.value = false
  try {
    const result = await apiFetch<MatchAdministration>(path.value)
    data.value = result
    // Refresh never silently discards a note the organizer is still editing.
    if (initial) note.value = result.note
    score1.value = result.result.score[0] ?? null
    score2.value = result.result.score[1] ?? null
    needsRefresh.value = false
    syncAction()
  } catch (e) {
    error.value = formatApiError(e)
    needsRefresh.value = true
  } finally {
    loading.value = false
  }
}
async function save(kind: MatchAdminAction | 'note') {
  if (busy.value || needsRefresh.value || !data.value) return
  if (kind !== 'note' && (!reviewing.value || !valid.value)) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const result = await apiFetch<MatchAdministration>(path.value, {
      method: 'POST',
      body: JSON.stringify({
        action: kind,
        version: data.value.version,
        note: note.value,
        reason: reason.value.trim(),
        confirm: kind !== 'note',
        participant_id: participantId.value,
        score1: score1.value,
        score2: score2.value,
        refund: kind === 'disqualify' && returnFee.value,
      }),
    })
    data.value = result
    if (kind === 'note') note.value = result.note
    if (kind !== 'note') {
      reason.value = ''
      returnFee.value = false
      reviewing.value = false
    }
    success.value = t(kind === 'note' ? 'matchAdmin.noteSaved' : 'matchAdmin.saved')
    syncAction()
    emit('saved')
  } catch (e) {
    error.value = formatApiError(e)
    // An uncertain response must never trigger an automatic financial/result retry.
    if (!(e instanceof ApiError) || e.status === 409 || e.status >= 500) needsRefresh.value = true
    reviewing.value = false
  } finally {
    busy.value = false
  }
}
function selectAll(event: Event) {
  ;(event.target as HTMLInputElement)?.select?.()
}
onMounted(() => load(true))
</script>

<template>
  <div class="match-admin" :aria-busy="busy || loading">
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <div v-if="error" role="alert" class="match-admin__error">{{ error }}</div>
    <div v-if="needsRefresh" class="match-admin__refresh">
      <p>{{ t('matchAdmin.refreshHint') }}</p>
      <Button
        :label="t('common.refresh')"
        size="small"
        outlined
        :disabled="busy || loading"
        @click="load(!data)"
      />
    </div>
    <p v-if="success" role="status" class="match-admin__success">{{ success }}</p>
    <template v-if="data && !loading">
      <div
        v-if="data.needs_admin_adjudication"
        class="match-admin__adjudication"
        role="alert"
      >
        <strong>{{ t('matchAdmin.adjudicationTitle') }}</strong>
        <span>{{ t('matchAdmin.adjudicationBothMissing') }}</span>
      </div>
      <section v-show="section === 'score' || section === 'players'" class="match-admin__section">
        <h3>{{ t(`matchDetails.sections.${section === 'players' ? 'players' : 'score'}`) }}</h3>
        <p v-if="!data.can_rule" class="match-admin__hint">{{ t('matchAdmin.locked') }}</p>
        <form v-if="options.length" @submit.prevent="reviewing = valid">
          <fieldset :disabled="busy || needsRefresh || reviewing">
            <div
              v-if="section === 'players' || options.length > 1"
              class="match-admin__action-choices"
              role="group"
              :aria-label="t('matchAdmin.action')"
            >
              <Button
                v-for="option in options"
                :key="option.value"
                type="button"
                :label="option.label"
                :icon="actionIcons[option.value]"
                :data-action="option.value"
                :aria-pressed="action === option.value"
                :outlined="action !== option.value"
                :severity="option.value === 'disqualify' ? 'danger' : 'secondary'"
                :disabled="busy || needsRefresh || reviewing"
                @click="action = option.value"
              />
            </div>
            <div v-if="isScoreAction" class="match-admin__scores">
              <div v-for="(player, index) in data.players" :key="player.id">
                <label :for="`${prefix}-score-${index}`">{{ player.name }}</label>
                <InputNumber
                  v-if="index === 0"
                  v-model="score1"
                  :input-id="`${prefix}-score-${index}`"
                  :min="0"
                  :max="32767"
                  :max-fraction-digits="0"
                  :use-grouping="false"
                  :disabled="busy || needsRefresh || reviewing"
                  @focus="selectAll"
                  @click="selectAll"
                />
                <InputNumber
                  v-else
                  v-model="score2"
                  :input-id="`${prefix}-score-${index}`"
                  :min="0"
                  :max="32767"
                  :max-fraction-digits="0"
                  :use-grouping="false"
                  :disabled="busy || needsRefresh || reviewing"
                  @focus="selectAll"
                  @click="selectAll"
                />
              </div>
            </div>
            <template v-else>
              <label :for="`${prefix}-player`">{{
                t(action === 'disqualify' ? 'matchAdmin.disqualifiedPlayer' : 'matchAdmin.player')
              }}</label>
              <Select
                :input-id="`${prefix}-player`"
                v-model="participantId"
                :options="playerOptions"
                option-label="name"
                option-value="id"
                :placeholder="t('matchAdmin.choosePlayer')"
                :disabled="busy || needsRefresh || reviewing"
              />
            </template>
            <label
              v-if="
                action === 'disqualify' && selectedPlayer && Number(selectedPlayer.refundable) > 0
              "
              class="match-admin__refund"
              :for="`${prefix}-refund`"
            >
              <Checkbox
                v-model="returnFee"
                binary
                :input-id="`${prefix}-refund`"
                :disabled="busy || needsRefresh || reviewing"
              />
              <span
                >{{ t('matchAdmin.refundOption', { amount: refundAmount })
                }}<small>{{ t('matchAdmin.walletOnly') }}</small></span
              >
            </label>
            <p
              v-if="
                action === 'disqualify' && selectedPlayer && Number(selectedPlayer.refundable) <= 0
              "
              class="match-admin__hint"
            >
              {{ t('matchAdmin.noRefund') }}
            </p>
            <label :for="`${prefix}-reason`">{{ t('matchAdmin.reason') }}</label>
            <Textarea
              :id="`${prefix}-reason`"
              v-model="reason"
              maxlength="1000"
              rows="2"
              required
              :disabled="busy || needsRefresh || reviewing"
            />
            <small>{{ t(terminalAction ? 'matchAdmin.sharedReason' : 'matchAdmin.private') }}</small>
          </fieldset>
          <Button
            v-if="!reviewing"
            type="submit"
            :label="t('matchAdmin.review')"
            :disabled="!valid"
            :severity="action === 'disqualify' ? 'danger' : 'primary'"
          />
        </form>
        <section v-if="reviewing" class="match-admin__confirmation" aria-live="polite">
          <h4>{{ t('matchAdmin.confirmTitle') }}</h4>
          <p>{{ confirmation }}</p>
          <p v-if="action === 'disqualify'">
            {{
              t(returnFee ? 'matchAdmin.confirmRefund' : 'matchAdmin.noAutomaticRefund', {
                name: selectedPlayer?.name ?? '',
                amount: refundAmount,
              })
            }}
          </p>
            <p v-if="terminalAction && action !== 'refund'" class="match-admin__hint">
            {{ t('matchAdmin.finalWarning') }}
          </p>
          <div class="match-admin__buttons">
            <Button
              :label="t('matchAdmin.cancel')"
              severity="secondary"
              outlined
              :disabled="busy"
              @click="reviewing = false"
            />
            <Button
              data-testid="confirm-ruling"
              :label="t('matchAdmin.confirm')"
              :severity="action === 'disqualify' ? 'danger' : 'primary'"
              :loading="busy"
              :disabled="!valid"
              @click="save(action)"
            />
          </div>
        </section>
      </section>
      <MatchTimes v-if="section === 'times'" :times="data.times" />
      <div v-show="section === 'note'">
        <MatchInternalNote
          v-model="note"
          :input-id="`${prefix}-note`"
          :busy="busy"
          :disabled="needsRefresh || reviewing"
          :unchanged="note.trim() === data.note"
          @save="save('note')"
        />
      </div>
      <MatchAuditHistory
        v-if="section === 'history'"
        :events="data.history"
        :players="data.players"
        expanded
      />
    </template>
  </div>
</template>

<style scoped>
.match-admin {
  display: grid;
  gap: 16px;
  margin-top: 20px;
  font-size: 13px;
}
.match-admin__adjudication {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid #f59e0b;
  border-radius: 10px;
  color: #fef3c7;
  background: #451a03;
}
.match-admin__section {
  padding: 16px;
  border: 1px solid #2b3e5e;
  border-radius: 12px;
  background: #142137;
}
.match-admin__action-choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}
.match-admin__action-choices :deep(button) {
  flex: 1 1 130px;
  font-size: 12px;
}
h3,
h4 {
  font-size: 14px;
  font-weight: 650;
  margin-bottom: 12px;
}
form,
fieldset {
  display: grid;
  gap: 10px;
}
fieldset {
  border: 0;
  margin: 0 0 14px;
  padding: 0;
  min-width: 0;
}
label {
  font-size: 12px;
  font-weight: 600;
}
small {
  color: #a7b9d0;
  font-size: 11px;
}
.match-admin__scores {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.match-admin__scores > div {
  display: grid;
  gap: 8px;
  min-width: 0;
}
:deep(.p-inputnumber),
:deep(.p-select) {
  width: 100%;
  min-width: 0;
}
:deep(.p-inputnumber-input),
:deep(.p-select),
textarea {
  background: #0e1729;
  color: #edf3ff;
  border: 1px solid #36516f;
  border-radius: 7px;
}
:deep(.p-inputnumber-input),
textarea {
  padding: 10px;
  width: 100%;
  min-width: 0;
}
textarea {
  resize: vertical;
}
.match-admin__refund {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  background: #173a35;
  border: 1px solid #2e6757;
  border-radius: 8px;
  cursor: pointer;
}
.match-admin__refund small {
  display: block;
  margin-top: 4px;
}
.match-admin__hint {
  color: #aebed3;
  line-height: 1.6;
  margin: 8px 0 12px;
}
.match-admin__confirmation {
  padding: 16px;
  background: #302a21;
  border: 1px solid #816843;
  border-radius: 10px;
  line-height: 1.7;
}
.match-admin__buttons {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}
.match-admin__error {
  color: #ffb3b3;
  background: #3a1c29;
  padding: 12px;
  border-radius: 8px;
  overflow-wrap: anywhere;
}
.match-admin__success {
  color: #92ebc9;
  background: #143b33;
  padding: 12px;
  border-radius: 8px;
}
.match-admin__refresh {
  display: grid;
  justify-items: start;
  gap: 10px;
  color: #f1ce8c;
}
</style>
