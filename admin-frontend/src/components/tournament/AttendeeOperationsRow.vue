<script setup lang="ts">
import { ref, watch } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import UserQuickView from '@/components/UserQuickView.vue'
import { useI18n } from '@/i18n'

export interface OperationalAttendee {
  id: number
  name: string
  username?: string | null
  user_id: number | null
  status: 'registered' | 'waitlisted' | 'withdrawn' | 'disqualified'
  payment_status: 'paid' | 'unpaid' | 'waived' | 'refunded'
  refundable?: string
  checked_in_at: string | null
  withdrawn_at?: string | null
  internal_note: string
  disqualified?: boolean
  requires_attention: boolean
  attention_reasons: string[]
  slot?: number | null
}

const props = defineProps<{
  attendee: OperationalAttendee
  selected: boolean
  disabled?: boolean
  canChangeRoster?: boolean
  canPromote?: boolean
}>()
const emit = defineEmits<{
  select: [id: number, selected: boolean]
  action: [action: string, ids: number[]]
  note: [id: number, note: string]
}>()
const { t } = useI18n()
const note = ref(props.attendee.internal_note || '')
watch(() => props.attendee.internal_note, value => { note.value = value || '' })

const statusKey = (status: OperationalAttendee['status']) => ({
  registered: 'attendees.statusRegistered',
  waitlisted: 'attendees.statusWaitlisted',
  withdrawn: 'attendees.statusWithdrawn',
  disqualified: 'attendees.statusDisqualified',
}[status])
const paymentKey = (status: OperationalAttendee['payment_status']) => ({
  paid: 'attendees.paymentPaid',
  unpaid: 'attendees.paymentUnpaid',
  waived: 'attendees.paymentWaived',
  refunded: 'attendees.paymentRefunded',
}[status])
</script>

<template>
  <article :class="['operations-row', { 'operations-row--attention': attendee.requires_attention }]">
    <label class="operations-row__select">
      <input
        type="checkbox"
        :checked="selected"
        :disabled="disabled"
        :aria-label="t('attendees.selectNamed', { name: attendee.name })"
        @change="emit('select', attendee.id, ($event.target as HTMLInputElement).checked)"
      />
    </label>

    <div class="operations-row__identity">
      <span class="operations-row__avatar" aria-hidden="true">{{ (attendee.name.trim()[0] || '?').toUpperCase() }}</span>
      <div class="min-w-0">
        <UserQuickView :user-id="attendee.user_id" :username="attendee.username || attendee.name" />
        <p class="operations-row__meta">
          <span v-if="attendee.slot">#{{ attendee.slot }}</span>
          <span>{{ attendee.user_id ? t('attendees.registeredUser') : t('attendees.virtualAttendee') }}</span>
        </p>
      </div>
    </div>

    <div class="operations-row__statuses">
      <span :class="['status-chip', `status-chip--${attendee.status}`]">{{ t(statusKey(attendee.status)) }}</span>
      <span :class="['status-chip', `status-chip--${attendee.payment_status}`]">{{ t(paymentKey(attendee.payment_status)) }}</span>
      <span :class="['status-chip', attendee.checked_in_at ? 'status-chip--checked' : 'status-chip--pending']">
        {{ t(attendee.checked_in_at ? 'attendees.checkedIn' : 'attendees.notCheckedIn') }}
      </span>
    </div>

    <div class="operations-row__actions">
      <template v-if="attendee.status === 'registered'">
        <Button
          size="small"
          :icon="attendee.checked_in_at ? 'bi bi-arrow-counterclockwise' : 'bi bi-check2-circle'"
          :label="t(attendee.checked_in_at ? 'attendees.undoCheckIn' : 'attendees.checkIn')"
          :severity="attendee.checked_in_at ? 'secondary' : 'success'"
          outlined
          :disabled="disabled"
          @click="emit('action', attendee.checked_in_at ? 'undo_check_in' : 'check_in', [attendee.id])"
        />
        <Button
          v-if="attendee.payment_status === 'unpaid'"
          size="small"
          icon="bi bi-cash-coin"
          :label="t('attendees.markPaid')"
          severity="warn"
          outlined
          :disabled="disabled"
          @click="emit('action', 'mark_paid', [attendee.id])"
        />
        <Button
          v-else
          size="small"
          icon="bi bi-cash-stack"
          :label="t('attendees.markUnpaid')"
          severity="secondary"
          text
          :disabled="disabled"
          @click="emit('action', 'mark_unpaid', [attendee.id])"
        />
        <Button
          size="small"
          icon="bi bi-slash-circle"
          :aria-label="t('attendees.disqualifyNamed', { name: attendee.name })"
          severity="danger"
          text
          :disabled="disabled || !canChangeRoster"
          @click="emit('action', 'disqualify', [attendee.id])"
        />
        <Button
          size="small"
          icon="bi bi-person-x"
          :aria-label="t('attendees.withdrawNamed', { name: attendee.name })"
          severity="danger"
          text
          :disabled="disabled || !canChangeRoster"
          @click="emit('action', 'withdraw', [attendee.id])"
        />
      </template>
      <Button
        v-else-if="attendee.status === 'waitlisted'"
        size="small"
        icon="bi bi-arrow-up-circle"
        :label="t('attendees.promote')"
        severity="success"
        :disabled="disabled || !canPromote"
        @click="emit('action', 'promote', [attendee.id])"
      />
      <Button
        v-else-if="attendee.status === 'withdrawn' || attendee.status === 'disqualified'"
        size="small"
        icon="bi bi-arrow-repeat"
        :label="t('attendees.restore')"
        severity="secondary"
        outlined
        :disabled="disabled || !canPromote"
        @click="emit('action', 'restore', [attendee.id])"
      />
    </div>

    <form class="operations-row__note" @submit.prevent="emit('note', attendee.id, note)">
      <InputText v-model="note" :placeholder="t('attendees.internalNote')" :disabled="disabled" maxlength="1000" />
      <Button
        type="submit"
        icon="bi bi-floppy"
        text
        :aria-label="t('attendees.saveNote')"
        :disabled="disabled || note === attendee.internal_note"
      />
    </form>
  </article>
</template>

<style scoped>
.operations-row { display: grid; grid-template-columns: auto minmax(190px, 1.25fr) minmax(210px, 1fr) auto; align-items: center; gap: 12px 16px; padding: 14px 16px; border: 1px solid #2b3c59; border-radius: 12px; background: #121d32; }
.operations-row--attention { border-color: #66512d; box-shadow: inset 3px 0 #d2a746; }
.operations-row__select input { width: 16px; height: 16px; accent-color: #60a5fa; }
.operations-row__identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.operations-row__avatar { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border-radius: 10px; background: #253a5b; color: #b9dcff; font-weight: 800; }
.operations-row__meta { display: flex; gap: 8px; margin: 3px 0 0; color: #8196b4; font-size: 11px; }
.operations-row__statuses { display: flex; flex-wrap: wrap; gap: 6px; }
.status-chip { display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border: 1px solid #415270; border-radius: 999px; color: #b7c5d9; font-size: 10px; font-weight: 700; }
.status-chip--registered, .status-chip--paid, .status-chip--checked { border-color: #286856; background: #17382f; color: #86e3c0; }
.status-chip--waitlisted, .status-chip--unpaid, .status-chip--pending { border-color: #6f582b; background: #3b301c; color: #f1ce75; }
.status-chip--withdrawn, .status-chip--refunded { background: #273247; color: #aebbd0; }
.status-chip--disqualified { border-color: #7a3f4c; background: #3c222e; color: #ffb3c0; }
.status-chip--waived { border-color: #3b5680; background: #20334f; color: #a9ceff; }
.operations-row__actions { display: flex; justify-content: flex-end; gap: 6px; }
.operations-row__actions :deep(.p-button-label) { white-space: nowrap; }
.operations-row__note { grid-column: 2 / -1; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px; }
.operations-row__note :deep(input) { width: 100%; border-color: #2a3c5a; background: #0d1729; color: #dce8f8; font-size: 12px; }
@media (max-width: 860px) {
  .operations-row { grid-template-columns: auto minmax(0, 1fr); }
  .operations-row__statuses, .operations-row__actions, .operations-row__note { grid-column: 2; justify-content: flex-start; }
}
@media (max-width: 520px) {
  .operations-row__actions { flex-wrap: wrap; }
  .operations-row__actions :deep(.p-button) { flex: 1; }
}
</style>
