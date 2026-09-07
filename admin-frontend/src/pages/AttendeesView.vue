<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import AppAlert from '@/components/AppAlert.vue'
import AttendeeOperationsRow, {
  type OperationalAttendee,
} from '@/components/tournament/AttendeeOperationsRow.vue'
import AttendeeUserRow from '@/components/tournament/AttendeeUserRow.vue'
import AddPlayerDialog from '@/components/tournament/AddPlayerDialog.vue'
import RosterRemovalDialog from '@/components/tournament/RosterRemovalDialog.vue'
import WalletTopUpDialog from '@/components/tournament/WalletTopUpDialog.vue'
import { useTournamentWorkspace } from '@/composables/useTournamentWorkspace'
import { useI18n } from '@/i18n'
import { apiFetch, ApiError, formatApiError } from '@/services/api'

interface AvailableUser {
  id: number
  username: string
  phone_number?: string
  balance?: string | null
}

interface RegistrationSummary {
  registered: number
  checked_in: number
  unpaid: number
  waitlisted: number
  attention: number
  ready: number
}

interface TournamentData {
  state: string
  lifecycle_state?: string
  registration_open?: boolean
  registration_closed_reason?: string
  draw_confirmed_at?: string | null
  registration_summary?: RegistrationSummary
  entry_fee: string
  max_players: number | null
}

interface AttendeesResponse {
  participants: OperationalAttendee[]
  available: AvailableUser[]
  summary?: RegistrationSummary
  tournament: TournamentData
}

const emptySummary = (): RegistrationSummary => ({
  registered: 0,
  checked_in: 0,
  unpaid: 0,
  waitlisted: 0,
  attention: 0,
  ready: 0,
})
const route = useRoute()
const workspace = useTournamentWorkspace()
const { t, locale } = useI18n()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const success = ref('')
const balanceError = ref('')
const participants = ref<OperationalAttendee[]>([])
const available = ref<AvailableUser[]>([])
const summary = ref<RegistrationSummary>(emptySummary())
const tournament = ref<TournamentData | null>(null)
const q = ref('')
const filter = ref<'all' | 'attention' | 'registered' | 'waitlisted' | 'checked_in'>('all')
const selected = ref<number[]>([])
const pendingAction = ref<string | null>(null)
const topUpUser = ref<AvailableUser | null>(null)
const pendingUser = ref<AvailableUser | null>(null)
const pendingPreviouslyPaid = ref(false)
const addDialogError = ref('')
const removalRequest = ref<{
  action: 'withdraw' | 'disqualify'
  players: OperationalAttendee[]
} | null>(null)
const removalDialogError = ref('')

const entryFee = computed(() => Number(tournament.value?.entry_fee ?? 0))
const isFull = computed(() =>
  tournament.value?.max_players != null && summary.value.registered >= tournament.value.max_players,
)
const canAdd = computed(() =>
  tournament.value?.state === 'open' && !isFull.value && pendingAction.value === null && !loading.value,
)
const canChangeRoster = computed(() =>
  tournament.value?.state === 'open',
)
const canPromote = computed(() => canChangeRoster.value && !isFull.value)
const filteredParticipants = computed(() => participants.value.filter((participant) => {
  if (filter.value === 'attention') return participant.requires_attention
  if (filter.value === 'registered') return participant.status === 'registered'
  if (filter.value === 'waitlisted') return participant.status === 'waitlisted'
  if (filter.value === 'checked_in') return Boolean(participant.checked_in_at)
  return true
}))
const allVisibleSelected = computed(() =>
  filteredParticipants.value.length > 0 &&
  filteredParticipants.value.every(participant => selected.value.includes(participant.id)),
)
const selectedRegistered = computed(() => participants.value.filter(
  participant => selected.value.includes(participant.id) && participant.status === 'registered',
))
const feeLabel = computed(() => entryFee.value.toLocaleString(
  locale.value === 'he' ? 'he-IL' : 'en-US', { maximumFractionDigits: 2 },
))
const csvUrl = computed(() => {
  const query = q.value.trim() ? `&q=${encodeURIComponent(q.value.trim())}` : ''
  return `/tournaments-api/admin/tournaments/${id}/attendees?format=csv${query}`
})
const filters = computed(() => [
  { id: 'all' as const, label: t('attendees.filterAll'), count: participants.value.length },
  { id: 'attention' as const, label: t('attendees.filterAttention'), count: summary.value.attention },
  { id: 'registered' as const, label: t('attendees.filterRegistered'), count: summary.value.registered },
  { id: 'waitlisted' as const, label: t('attendees.filterWaitlisted'), count: summary.value.waitlisted },
  { id: 'checked_in' as const, label: t('attendees.filterCheckedIn'), count: summary.value.checked_in },
])
const hasRetainedPayment = (userId: number) => participants.value.some(participant =>
  participant.user_id === userId &&
  participant.status === 'withdrawn' &&
  participant.payment_status === 'paid',
)

async function load() {
  loading.value = true
  error.value = ''
  balanceError.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    const data = await apiFetch<AttendeesResponse>(`/api/admin/tournaments/${id}/attendees${qs}`)
    participants.value = data.participants
    available.value = data.available
    tournament.value = data.tournament
    summary.value = data.summary ?? data.tournament.registration_summary ?? {
      ...emptySummary(), registered: data.participants.filter(item => item.status === 'registered').length,
    }
    selected.value = selected.value.filter(participantId =>
      participants.value.some(participant => participant.id === participantId),
    )
    if (available.value.some(user => user.balance == null)) {
      try {
        const users = await apiFetch<{ id: number; balance: string }[]>(`/api/admin/users${qs}`)
        const balances = new Map(users.map(user => [user.id, user.balance]))
        available.value = available.value.map(user => ({
          ...user,
          balance: user.balance ?? balances.get(user.id) ?? null,
        }))
      } catch {
        balanceError.value = t('attendees.balanceLoadFailed')
      }
    }
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function setSelected(participantId: number, value: boolean) {
  selected.value = value
    ? [...new Set([...selected.value, participantId])]
    : selected.value.filter(idValue => idValue !== participantId)
}
function toggleVisible() {
  const visibleIds = filteredParticipants.value.map(participant => participant.id)
  selected.value = allVisibleSelected.value
    ? selected.value.filter(idValue => !visibleIds.includes(idValue))
    : [...new Set([...selected.value, ...visibleIds])]
}

async function runAction(action: string, participantIds = selected.value, extra = {}) {
  if (!participantIds.length || pendingAction.value) return false
  pendingAction.value = `${action}-${participantIds.join('-')}`
  error.value = ''
  success.value = ''
  try {
    await apiFetch(`/api/admin/tournaments/${id}/attendees`, {
      method: 'PATCH',
      body: JSON.stringify({ participant_ids: participantIds, action, ...extra }),
    })
    await load()
    await workspace?.refresh()
    success.value = t('attendees.operationSaved', { count: participantIds.length })
    if (['withdraw', 'disqualify', 'promote', 'restore'].includes(action)) selected.value = []
    return true
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
    return false
  } finally {
    pendingAction.value = null
  }
}

function requestAction(action: string, participantIds: number[]) {
  if (action === 'withdraw' || action === 'disqualify') {
    const players = participants.value.filter(participant => participantIds.includes(participant.id))
    if (!players.length || pendingAction.value) return
    removalDialogError.value = ''
    removalRequest.value = { action, players }
    return
  }
  if (action === 'restore' && participantIds.length === 1) {
    const participant = participants.value.find(item => item.id === participantIds[0])
    const user = available.value.find(item => item.id === participant?.user_id)
    if (participant?.status === 'withdrawn' && user) {
      requestAdd(user.id)
      return
    }
  }
  void runAction(action, participantIds)
}

async function confirmRemoval(refund: boolean) {
  const request = removalRequest.value
  if (!request || pendingAction.value) return
  removalDialogError.value = ''
  const succeeded = await runAction(
    request.action,
    request.players.map(player => player.id),
    { refund },
  )
  if (succeeded) removalRequest.value = null
  else removalDialogError.value = error.value
}

async function saveNote(participantId: number, note: string) {
  await runAction('update_note', [participantId], { note })
}

function requestAdd(userId: number) {
  const user = available.value.find(item => item.id === userId)
  if (!canAdd.value || !user) return
  const previouslyPaid = hasRetainedPayment(userId)
  if (!previouslyPaid && entryFee.value > 0 && (
    user.balance == null ||
    !Number.isFinite(Number(user.balance)) ||
    Math.round(Number(user.balance) * 100) < Math.round(entryFee.value * 100)
  )) return
  addDialogError.value = ''
  pendingPreviouslyPaid.value = previouslyPaid
  pendingUser.value = user
}

async function confirmAddUser(chargeAgain = false) {
  const user = pendingUser.value
  if (!canAdd.value || !user) return
  const userId = user.id
  pendingAction.value = `user-${userId}`
  error.value = ''
  success.value = ''
  try {
    await apiFetch(`/api/admin/tournaments/${id}/attendees`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, charge_again: chargeAgain }),
    })
    pendingUser.value = null
    await load()
    await workspace?.refresh()
    success.value = t('attendees.playerAdded', { name: user.username })
  } catch (caught: unknown) {
    if (caught instanceof ApiError && /insufficient[_ ](?:funds|balance)/i.test(caught.body)) {
      await load()
      pendingUser.value = null
      topUpUser.value = available.value.find(item => item.id === user.id) ?? user
      error.value = t('attendees.fundingChanged', { name: user.username })
    } else {
      addDialogError.value = formatApiError(caught)
    }
  } finally {
    pendingAction.value = null
  }
}

function topUpFromAdd() {
  if (!pendingUser.value) return
  topUpUser.value = pendingUser.value
  pendingUser.value = null
}

async function topUpSaved(balance: string) {
  const user = topUpUser.value
  if (!user) return
  user.balance = balance
  topUpUser.value = null
  await load()
  success.value = t('attendees.topUpSaved', { name: user.username })
}
</script>

<template>
  <div class="attendees-page mx-auto w-full max-w-6xl">
    <header class="attendees-heading">
      <div>
        <p class="attendees-heading__eyebrow">{{ t('attendees.operationsEyebrow') }}</p>
        <h2>{{ t('attendees.manage') }}</h2>
        <p>{{ t('attendees.subtitle') }}</p>
      </div>
      <div class="attendees-heading__actions">
        <a :href="csvUrl" class="export-link" download>
          <i class="bi bi-download" aria-hidden="true"></i>{{ t('attendees.exportCsv') }}
        </a>
        <Button :label="t('common.refresh')" icon="bi bi-arrow-clockwise" size="small" severity="secondary" outlined :disabled="pendingAction !== null" @click="load" />
      </div>
    </header>

    <div v-if="loading" class="attendees-loading">
      <i class="bi bi-arrow-clockwise" aria-hidden="true"></i><span>{{ t('common.loading') }}</span>
    </div>
    <div v-else class="attendees-content">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error = ''" />
      <AppAlert v-if="success" type="success" :message="success" dismissible @close="success = ''" />
      <AppAlert v-if="balanceError" type="error" :message="balanceError" />

      <section class="readiness-grid" :aria-label="t('attendees.readinessSummary')">
        <article><span><i class="bi bi-people"></i></span><strong>{{ summary.registered }}</strong><p>{{ t('attendees.summaryRegistered') }}</p></article>
        <article><span><i class="bi bi-person-check"></i></span><strong>{{ summary.checked_in }}/{{ summary.registered }}</strong><p>{{ t('attendees.summaryCheckedIn') }}</p></article>
        <article :class="{ 'metric--attention': summary.unpaid > 0 }"><span><i class="bi bi-wallet2"></i></span><strong>{{ summary.unpaid }}</strong><p>{{ t('attendees.summaryUnpaid') }}</p></article>
        <article :class="{ 'metric--attention': summary.waitlisted > 0 }"><span><i class="bi bi-hourglass-split"></i></span><strong>{{ summary.waitlisted }}</strong><p>{{ t('attendees.summaryWaitlisted') }}</p></article>
        <article :class="summary.attention ? 'metric--attention' : 'metric--ready'"><span><i class="bi bi-flag"></i></span><strong>{{ summary.attention }}</strong><p>{{ t('attendees.summaryAttention') }}</p></article>
      </section>

      <div class="fee-strip">
        <span><i class="bi bi-cash-coin"></i></span>
        <div><strong>{{ t('attendees.entryFee', { amount: feeLabel }) }}</strong><p>{{ t(entryFee > 0 ? 'attendees.chargeHint' : 'attendees.freeEntry') }}</p></div>
      </div>

      <AppAlert v-if="isFull" type="warning" :message="t('attendees.capacityReached')" />

      <section class="roster-panel" aria-labelledby="registered-heading">
        <header class="roster-panel__header">
          <div><p class="panel-eyebrow">{{ t('attendees.rosterEyebrow') }}</p><h3 id="registered-heading">{{ t('attendees.registered') }}</h3></div>
          <div class="roster-search"><InputText v-model="q" :placeholder="t('attendees.searchRoster')" @keydown.enter="load" /><Button icon="bi bi-search" severity="secondary" outlined :aria-label="t('common.search')" @click="load" /></div>
        </header>

        <nav class="roster-filters" :aria-label="t('attendees.filters')">
          <button v-for="item in filters" :key="item.id" type="button" :class="{ active: filter === item.id }" @click="filter = item.id">{{ item.label }} <span>{{ item.count }}</span></button>
        </nav>

        <div v-if="selected.length" class="bulk-bar">
          <label><input type="checkbox" :checked="allVisibleSelected" @change="toggleVisible" />{{ t('attendees.selectedCount', { count: selected.length }) }}</label>
          <div>
            <Button size="small" icon="bi bi-check2-circle" :label="t('attendees.checkIn')" severity="success" :disabled="!selectedRegistered.length || pendingAction !== null" @click="runAction('check_in', selectedRegistered.map(item => item.id))" />
            <Button size="small" icon="bi bi-cash-coin" :label="t('attendees.markPaid')" severity="warn" outlined :disabled="!selectedRegistered.length || pendingAction !== null" @click="runAction('mark_paid', selectedRegistered.map(item => item.id))" />
            <Button size="small" :label="t('attendees.waivePayment')" severity="secondary" outlined :disabled="!selectedRegistered.length || pendingAction !== null" @click="runAction('waive_payment', selectedRegistered.map(item => item.id))" />
            <Button size="small" icon="bi bi-slash-circle" :label="t('attendees.disqualify')" severity="danger" text :disabled="!selectedRegistered.length || !canChangeRoster || pendingAction !== null" @click="requestAction('disqualify', selectedRegistered.map(item => item.id))" />
            <Button size="small" icon="bi bi-person-x" :label="t('attendees.withdraw')" severity="danger" text :disabled="!selectedRegistered.length || !canChangeRoster || pendingAction !== null" @click="requestAction('withdraw', selectedRegistered.map(item => item.id))" />
          </div>
        </div>
        <label v-else-if="filteredParticipants.length" class="select-visible"><input type="checkbox" :checked="allVisibleSelected" @change="toggleVisible" />{{ t('attendees.selectVisible') }}</label>

        <div v-if="filteredParticipants.length" class="operations-list">
          <AttendeeOperationsRow v-for="participant in filteredParticipants" :key="participant.id" :attendee="participant" :selected="selected.includes(participant.id)" :disabled="pendingAction !== null" :can-change-roster="canChangeRoster" :can-promote="canPromote" @select="setSelected" @action="requestAction" @note="saveNote" />
        </div>
        <div v-else class="empty-state"><i class="bi bi-person-plus"></i><p>{{ t('attendees.noMatchingParticipants') }}</p></div>
      </section>

      <section v-if="tournament?.state === 'open'" class="add-panel" aria-labelledby="add-attendees-heading">
        <header><div><p class="panel-eyebrow">{{ t('attendees.registrationEyebrow') }}</p><h3 id="add-attendees-heading">{{ t('attendees.add') }}</h3><p>{{ t('attendees.addSubtitle') }}</p></div></header>
        <div class="available-list">
          <AttendeeUserRow v-for="user in available" :key="user.id" :user="user" :entry-fee="hasRetainedPayment(user.id) ? 0 : entryFee" :disabled="!canAdd" :loading="pendingAction === `user-${user.id}`" @add="requestAdd" @top-up="topUpUser = user" />
          <div v-if="available.length === 0" class="empty-state"><i class="bi bi-search"></i><p>{{ t('attendees.noAvailable') }}</p></div>
        </div>
      </section>
    </div>

    <WalletTopUpDialog v-if="topUpUser" :key="topUpUser.id" :user="topUpUser" :entry-fee="entryFee" @close="topUpUser = null" @saved="topUpSaved" />
    <AddPlayerDialog
      v-if="pendingUser" :key="pendingUser.id" :user="pendingUser" :entry-fee="entryFee" :previously-paid="pendingPreviouslyPaid"
      :busy="pendingAction === `user-${pendingUser.id}`" :error="addDialogError"
      @cancel="pendingUser = null" @confirm="confirmAddUser" @top-up="topUpFromAdd"
    />
    <RosterRemovalDialog
      v-if="removalRequest" :key="`${removalRequest.action}-${removalRequest.players.map(player => player.id).join('-')}`"
      :players="removalRequest.players" :action="removalRequest.action" :busy="pendingAction !== null"
      :error="removalDialogError" @cancel="removalRequest = null" @confirm="confirmRemoval"
    />
  </div>
</template>

<style scoped>
.attendees-page { padding-block: 8px 32px; }
.attendees-content { display: grid; gap: 16px; }
.attendees-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; padding-bottom: 18px; border-bottom: 1px solid #263653; }
.attendees-heading h2 { margin: 2px 0 0; color: #eef3ff; font-size: 22px; font-weight: 750; }
.attendees-heading p:not(.attendees-heading__eyebrow) { margin: 5px 0 0; color: #92a5c0; font-size: 13px; }
.attendees-heading__eyebrow, .panel-eyebrow { margin: 0; color: #6faeea; font-size: 10px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
.attendees-heading__actions { display: flex; gap: 8px; }
.export-link { display: inline-flex; align-items: center; gap: 7px; min-height: 34px; padding: 6px 11px; border: 1px solid #3b4d6b; border-radius: 8px; color: #c6d4e8; font-size: 12px; font-weight: 650; }
.export-link:hover { border-color: #659bd2; color: #e7f2ff; }
.readiness-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.readiness-grid article { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 2px 10px; min-height: 86px; padding: 14px; border: 1px solid #2c3d59; border-radius: 12px; background: #111b2f; }
.readiness-grid article > span { grid-row: 1 / 3; display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; background: #243754; color: #9dccff; }
.readiness-grid strong { color: #f0f5ff; font-size: 20px; line-height: 1; }
.readiness-grid p { margin: 3px 0 0; color: #8295b2; font-size: 10px; }
.readiness-grid .metric--attention { border-color: #66512d; }
.readiness-grid .metric--attention > span { background: #45391f; color: #efc969; }
.readiness-grid .metric--ready { border-color: #285e50; }
.readiness-grid .metric--ready > span { background: #1b4b40; color: #7ee0ba; }
.fee-strip { display: flex; align-items: center; gap: 12px; padding: 13px 16px; border: 1px solid #2b3d5a; border-radius: 11px; background: #152139; }
.fee-strip > span { color: #82bdf5; }
.fee-strip strong { color: #eaf2ff; font-size: 13px; }
.fee-strip p { margin: 2px 0 0; color: #879ab6; font-size: 11px; }
.roster-panel, .add-panel { overflow: hidden; border: 1px solid #293b59; border-radius: 14px; background: #0f192c; }
.roster-panel__header, .add-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 17px 18px; border-bottom: 1px solid #263751; background: #131f35; }
.roster-panel h3, .add-panel h3 { margin: 3px 0 0; color: #eef4ff; font-size: 16px; font-weight: 700; }
.add-panel header p:not(.panel-eyebrow) { margin: 4px 0 0; color: #879ab5; font-size: 11px; }
.roster-search { display: flex; gap: 6px; }
.roster-search :deep(input) { width: 210px; border-color: #344762; background: #0d1728; color: #e3ecf9; font-size: 12px; }
.roster-filters { display: flex; gap: 6px; overflow-x: auto; padding: 11px 16px; border-bottom: 1px solid #21324b; }
.roster-filters button { display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto; padding: 6px 9px; border: 1px solid transparent; border-radius: 8px; color: #8fa2bd; font-size: 11px; font-weight: 650; }
.roster-filters button span { display: grid; min-width: 19px; height: 19px; place-items: center; border-radius: 999px; background: #263750; color: #bfd0e6; font-size: 9px; }
.roster-filters button.active { border-color: #37628d; background: #1d3652; color: #c8e4ff; }
.bulk-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 16px 0; padding: 10px 12px; border: 1px solid #365a7d; border-radius: 10px; background: #162d46; }
.bulk-bar label, .select-visible { display: flex; align-items: center; gap: 8px; color: #c3d9ef; font-size: 11px; font-weight: 650; }
.bulk-bar label input, .select-visible input { width: 15px; height: 15px; accent-color: #60a5fa; }
.bulk-bar > div { display: flex; flex-wrap: wrap; gap: 6px; }
.select-visible { width: fit-content; margin: 12px 16px 0; }
.operations-list { display: grid; gap: 9px; padding: 12px 16px 16px; }
.available-list { padding: 4px 16px 12px; }
.empty-state { display: grid; justify-items: center; gap: 7px; padding: 30px; color: #7186a5; text-align: center; }
.empty-state i { font-size: 23px; }
.empty-state p { margin: 0; font-size: 12px; }
.attendees-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 220px; color: #879ab7; }
.attendees-loading i { animation: spin 900ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .readiness-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .bulk-bar { align-items: flex-start; flex-direction: column; } }
@media (max-width: 600px) { .attendees-heading { flex-direction: column; } .attendees-heading__actions { width: 100%; } .attendees-heading__actions > * { flex: 1; justify-content: center; } .readiness-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .roster-panel__header { align-items: stretch; flex-direction: column; } .roster-search :deep(input) { width: 100%; } .roster-search { width: 100%; } .roster-search :deep(.p-inputtext) { flex: 1; } .bulk-bar > div :deep(.p-button) { flex: 1; } }
</style>
