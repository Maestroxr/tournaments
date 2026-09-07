<script setup lang="ts">
import { computed, ref } from 'vue'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  user: { id: number; username: string; balance?: string | null }
  entryFee: number
  previouslyPaid?: boolean
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ confirm: [chargeAgain: boolean]; cancel: []; topUp: [] }>()
const { t, locale } = useI18n()
const formatMoney = (value: number) => value.toLocaleString(
  locale.value === 'he' ? 'he-IL' : 'en-US',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 },
)
const balance = computed(() => Number(props.user.balance ?? 0))
const chargeAgain = ref(false)
const amountToCharge = computed(() => props.previouslyPaid && !chargeAgain.value ? 0 : props.entryFee)
const sufficientBalance = computed(() => balance.value >= amountToCharge.value)
const balanceAfter = computed(() => Math.max(0, balance.value - amountToCharge.value))
function cancel() { if (!props.busy) emit('cancel') }
</script>

<template>
  <Dialog
    :visible="true" modal append-to="self" class="attendee-confirm-dialog"
    :header="t('attendees.confirmAddTitle')" :dir="locale === 'he' ? 'rtl' : 'ltr'"
    :closable="!busy" :close-on-escape="!busy" :dismissable-mask="false"
    :style="{ width: '470px', maxWidth: 'calc(100vw - 32px)', background: '#111b30', color: '#edf3ff', border: '1px solid #2b3e5e', borderRadius: '20px' }"
    @update:visible="cancel"
  >
    <div class="attendee-confirm-dialog__person">
      <span aria-hidden="true">{{ (user.username.trim()[0] || '?').toUpperCase() }}</span>
      <div><strong>{{ user.username }}</strong><p>{{ t('attendees.confirmAddWarning') }}</p></div>
    </div>
    <dl class="attendee-confirm-dialog__amounts">
      <div><dt>{{ t('attendees.currentBalance') }}</dt><dd>{{ formatMoney(balance) }}</dd></div>
      <div><dt>{{ t('attendees.entryFeeLabel') }}</dt><dd class="is-charge">−{{ formatMoney(amountToCharge) }}</dd></div>
      <div><dt>{{ t('attendees.balanceAfterCharge') }}</dt><dd>{{ formatMoney(balanceAfter) }}</dd></div>
    </dl>
    <label v-if="previouslyPaid" class="attendee-confirm-dialog__choice" for="charge-player-again">
      <Checkbox v-model="chargeAgain" binary input-id="charge-player-again" :disabled="busy" />
      <span><strong>{{ t('attendees.chargeAgainOption', { amount: formatMoney(entryFee) }) }}</strong><small>{{ t('attendees.previousPaymentKept') }}</small></span>
    </label>
    <AppAlert v-if="!sufficientBalance" type="warning" :message="t('attendees.chargeAgainInsufficient')" />
    <AppAlert v-if="error" type="error" :message="error" />
    <template #footer>
      <div class="attendee-confirm-dialog__footer">
        <Button :label="t('common.cancel')" severity="secondary" outlined :disabled="busy" @click="cancel" />
        <Button v-if="!sufficientBalance" :label="t('attendees.topUp')" icon="bi bi-wallet2" severity="warn" :disabled="busy" @click="emit('topUp')" />
        <Button :label="t(previouslyPaid ? 'attendees.confirmRestoreAction' : 'attendees.confirmAddAction')" icon="bi bi-person-plus" severity="success" :loading="busy" :disabled="busy || !sufficientBalance" @click="emit('confirm', chargeAgain)" />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.attendee-confirm-dialog__person { display: flex; align-items: center; gap: 13px; padding: 15px; border: 1px solid #2b3e5e; border-radius: 13px; background: #17253d; }
.attendee-confirm-dialog__person > span { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 12px; background: #234467; color: #b9dcff; font-weight: 800; }
.attendee-confirm-dialog__person strong { color: #f3f7ff; }
.attendee-confirm-dialog__person p { margin: 4px 0 0; color: #a9bdd9; font-size: 12px; line-height: 1.45; }
.attendee-confirm-dialog__amounts { display: grid; gap: 9px; margin: 16px 0; }
.attendee-confirm-dialog__amounts div { display: flex; justify-content: space-between; gap: 16px; color: #aebed5; font-size: 13px; }
.attendee-confirm-dialog__amounts dd { margin: 0; color: #f0f5ff; font-weight: 700; }
.attendee-confirm-dialog__amounts .is-charge { color: #ffbd86; }
.attendee-confirm-dialog__choice { display: flex; align-items: flex-start; gap: 11px; margin: 16px 0; padding: 13px; border: 1px solid #385575; border-radius: 11px; background: #16283e; cursor: pointer; }
.attendee-confirm-dialog__choice span { display: grid; gap: 3px; }
.attendee-confirm-dialog__choice strong { color: #d8eaff; font-size: 13px; }
.attendee-confirm-dialog__choice small { color: #94a9c3; font-size: 11px; }
.attendee-confirm-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; width: 100%; }
</style>
