<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import AppAlert from '@/components/AppAlert.vue'
import AddPlayerDialog from '@/components/tournament/AddPlayerDialog.vue'
import AttendeeRosterRow, {
  type RosterAttendee,
} from '@/components/tournament/AttendeeRosterRow.vue'
import AttendeeUserRow from '@/components/tournament/AttendeeUserRow.vue'
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
  entry_fee: string
  max_players: number | null
  registration_summary?: RegistrationSummary
}

interface AttendeesResponse {
  participants: RosterAttendee[]
  available: AvailableUser[]
  summary?: RegistrationSummary
  tournament: TournamentData
}

const emptySummary = (): RegistrationSummary => ({
  registered: 0, checked_in: 0, unpaid: 0, waitlisted: 0, attention: 0, ready: 0,
})
const route = useRoute()
const workspace = useTournamentWorkspace()
const { t, locale } = useI18n()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const success = ref('')
const balanceError = ref('')
const participants = ref<RosterAttendee[]>([])
const available = ref<AvailableUser[]>([])
const summary = ref<RegistrationSummary>(emptySummary())
const tournament = ref<TournamentData | null>(null)
const search = ref('')
const pendingAction = ref<string | null>(null)
const topUpUser = ref<AvailableUser | null>(null)
const pendingUser = ref<AvailableUser | null>(null)
const pendingPreviouslyPaid = ref(false)
const addDialogError = ref('')
const removalRequest = ref<RosterAttendee[] | null>(null)
const removalDialogError = ref('')

const entryFee = computed(() => Number(tournament.value?.entry_fee ?? 0))
const activeParticipants = computed(() => participants.value.filter(item => item.status === 'registered'))
function phoneVariants(value: string) {
  const digits = value.replace(/\D/g, '')
  if (!digits) return []
  if (digits.startsWith('972') && digits.length > 3) return [digits, `0${digits.slice(3)}`]
  if (digits.startsWith('0') && digits.length > 1) return [digits, `972${digits.slice(1)}`]
  return [digits]
}
function matchesPhone(phone: string | undefined, query: string) {
  if (!phone || !/^[+\d\s()-]+$/.test(query)) return false
  const queries = phoneVariants(query)
  const phones = phoneVariants(phone)
  return queries.some(candidate => phones.some(value => value.includes(candidate)))
}
const filteredAvailable = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  if (!query) return available.value
  return available.value.filter(user =>
    user.username.toLocaleLowerCase().includes(query) || matchesPhone(user.phone_number, query),
  )
})
const isFull = computed(() =>
  tournament.value?.max_players != null && activeParticipants.value.length >= tournament.value.max_players,
)
const canChangeRoster = computed(() => tournament.value?.state === 'open')
const canAdd = computed(() =>
  canChangeRoster.value && !isFull.value && pendingAction.value === null && !loading.value,
)
const feeLabel = computed(() => entryFee.value.toLocaleString(
  locale.value === 'he' ? 'he-IL' : 'en-US', { maximumFractionDigits: 2 },
))
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
    const data = await apiFetch<AttendeesResponse>(`/api/admin/tournaments/${id}/attendees`)
    participants.value = data.participants
    available.value = data.available
    tournament.value = data.tournament
    summary.value = data.summary ?? data.tournament.registration_summary ?? {
      ...emptySummary(), registered: activeParticipants.value.length,
    }
    if (available.value.some(user => user.balance == null)) {
      try {
        const users = await apiFetch<{ id: number; balance: string }[]>('/api/admin/users')
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

function requestRemoval(participantId: number) {
  if (!canChangeRoster.value || pendingAction.value) return
  const participant = activeParticipants.value.find(item => item.id === participantId)
  if (!participant) return
  removalDialogError.value = ''
  removalRequest.value = [participant]
}

async function confirmRemoval(refund: boolean) {
  const players = removalRequest.value
  if (!players?.length || pendingAction.value) return
  pendingAction.value = `remove-${players[0]?.id}`
  error.value = ''
  success.value = ''
  removalDialogError.value = ''
  try {
    await apiFetch(`/api/admin/tournaments/${id}/attendees`, {
      method: 'PATCH',
      body: JSON.stringify({ participant_ids: players.map(player => player.id), action: 'withdraw', refund }),
    })
    removalRequest.value = null
    await load()
    await workspace?.refresh()
    success.value = t(refund ? 'attendees.playerRemovedAndRefunded' : 'attendees.playerRemoved', {
      name: players[0]?.name ?? '',
    })
  } catch (caught: unknown) {
    removalDialogError.value = formatApiError(caught)
  } finally {
    pendingAction.value = null
  }
}

function requestAdd(userId: number) {
  const user = available.value.find(item => item.id === userId)
  if (!canAdd.value || !user) return
  const previouslyPaid = hasRetainedPayment(userId)
  if (entryFee.value <= 0) {
    void addUser(user, false)
    return
  }
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
  if (!user) return
  await addUser(user, chargeAgain)
}

async function addUser(user: AvailableUser, chargeAgain: boolean) {
  if (!canAdd.value) return
  const usesDialog = pendingUser.value?.id === user.id
  pendingAction.value = `user-${user.id}`
  error.value = ''
  success.value = ''
  try {
    await apiFetch(`/api/admin/tournaments/${id}/attendees`, {
      method: 'POST',
      body: JSON.stringify({ user_id: user.id, charge_again: chargeAgain }),
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
      const message = formatApiError(caught)
      if (usesDialog) addDialogError.value = message
      else error.value = message
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
  <div class="attendees-page mx-auto w-full max-w-5xl">
    <header class="attendees-heading">
      <div>
        <p class="panel-eyebrow">{{ t('attendees.playersEyebrow') }}</p>
        <h2>{{ t('attendees.managePlayersSimple') }}</h2>
        <p>{{ t('attendees.managePlayersSimpleHint') }}</p>
      </div>
      <Button :label="t('common.refresh')" icon="bi bi-arrow-clockwise" size="small" severity="secondary" outlined :disabled="pendingAction !== null" @click="load" />
    </header>

    <div v-if="loading" class="attendees-loading">
      <i class="bi bi-arrow-clockwise" aria-hidden="true"></i><span>{{ t('common.loading') }}</span>
    </div>
    <div v-else class="attendees-content">
      <AppAlert v-if="error" type="error" :message="error" dismissible @close="error = ''" />
      <AppAlert v-if="success" type="success" :message="success" dismissible @close="success = ''" />
      <AppAlert v-if="balanceError" type="error" :message="balanceError" />
      <AppAlert v-if="isFull" type="warning" :message="t('attendees.capacityReached')" />

      <section class="players-panel" aria-labelledby="registered-heading">
        <header class="panel-header">
          <div>
            <h3 id="registered-heading">{{ t('attendees.registered') }}</h3>
            <p>{{ t('attendees.registeredCount', { count: activeParticipants.length }) }}</p>
          </div>
          <span class="fee-label">{{ t('attendees.entryFee', { amount: feeLabel }) }}</span>
        </header>
        <div v-if="activeParticipants.length" class="roster-list">
          <AttendeeRosterRow
            v-for="participant in activeParticipants" :key="participant.id"
            :attendee="participant" :removable="canChangeRoster"
            :loading="pendingAction === `remove-${participant.id}`"
            @remove="requestRemoval"
          />
        </div>
        <div v-else class="empty-state"><i class="bi bi-people"></i><p>{{ t('attendees.empty') }}</p></div>
      </section>

      <section v-if="canChangeRoster" class="players-panel" aria-labelledby="add-attendees-heading">
        <header class="panel-header panel-header--search">
          <div><h3 id="add-attendees-heading">{{ t('attendees.add') }}</h3><p>{{ t('attendees.addSubtitle') }}</p></div>
          <span class="player-search"><i class="bi bi-search" aria-hidden="true"></i><InputText v-model="search" :placeholder="t('attendees.searchUsers')" /></span>
        </header>
        <div class="available-list">
          <AttendeeUserRow
            v-for="user in filteredAvailable" :key="user.id" :user="user"
            :entry-fee="hasRetainedPayment(user.id) ? 0 : entryFee" :disabled="!canAdd"
            :loading="pendingAction === `user-${user.id}`" @add="requestAdd" @top-up="topUpUser = user"
          />
          <div v-if="filteredAvailable.length === 0" class="empty-state"><i class="bi bi-search"></i><p>{{ t('attendees.noAvailable') }}</p></div>
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
      v-if="removalRequest" :key="removalRequest[0]?.id" :players="removalRequest" action="withdraw"
      :busy="pendingAction !== null" :error="removalDialogError"
      @cancel="removalRequest = null" @confirm="confirmRemoval"
    />
  </div>
</template>

<style scoped>
.attendees-page { padding-block: 8px 32px; }
.attendees-content { display: grid; gap: 16px; }
.attendees-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; padding-bottom: 18px; border-bottom: 1px solid #263653; }
.attendees-heading h2 { margin: 3px 0 0; color: #eef3ff; font-size: 22px; font-weight: 750; }
.attendees-heading p:not(.panel-eyebrow) { margin: 5px 0 0; color: #92a5c0; font-size: 13px; }
.panel-eyebrow { margin: 0; color: #6faeea; font-size: 10px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
.players-panel { overflow: hidden; border: 1px solid #293b59; border-radius: 14px; background: #0f192c; }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 17px 18px; border-bottom: 1px solid #263751; background: #131f35; }
.panel-header h3 { margin: 0; color: #eef4ff; font-size: 16px; font-weight: 700; }
.panel-header p { margin: 4px 0 0; color: #879ab5; font-size: 11px; }
.fee-label { padding: 6px 9px; border-radius: 999px; background: #203653; color: #b9d9f7; font-size: 11px; font-weight: 700; }
.roster-list { display: grid; gap: 8px; padding: 14px; }
.available-list { padding: 4px 16px 12px; }
.player-search { display: flex; align-items: center; gap: 8px; min-width: 240px; padding-inline-start: 10px; border: 1px solid #344762; border-radius: 9px; background: #0d1728; color: #7188a7; }
.player-search :deep(input) { width: 100%; border: 0; background: transparent; color: #e3ecf9; box-shadow: none; font-size: 12px; }
.empty-state { display: grid; justify-items: center; gap: 7px; padding: 30px; color: #7186a5; text-align: center; }
.empty-state i { font-size: 23px; }
.empty-state p { margin: 0; font-size: 12px; }
.attendees-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 220px; color: #879ab7; }
.attendees-loading i { animation: spin 900ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 600px) { .attendees-heading, .panel-header--search { align-items: stretch; flex-direction: column; } .player-search { min-width: 0; width: 100%; } }
</style>
