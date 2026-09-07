<script setup lang="ts">
import { computed, ref } from 'vue'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  players: { id: number; name: string; refundable?: string }[]
  action: 'withdraw' | 'disqualify'
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ confirm: [refund: boolean]; cancel: [] }>()
const { t, locale } = useI18n()
const refundable = computed(() => props.players.reduce(
  (total, player) => total + Number(player.refundable ?? 0), 0,
))
const refund = ref(refundable.value > 0)
const amount = computed(() => refundable.value.toLocaleString(
  locale.value === 'he' ? 'he-IL' : 'en-US',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 },
))
const names = computed(() => props.players.map(player => player.name).join(', '))
function cancel() { if (!props.busy) emit('cancel') }
</script>

<template>
  <Dialog
    :visible="true" modal append-to="self" class="roster-removal-dialog"
    :header="t(action === 'withdraw' ? 'attendees.removeDialogTitle' : 'attendees.disqualifyDialogTitle')"
    :dir="locale === 'he' ? 'rtl' : 'ltr'" :closable="!busy" :close-on-escape="!busy"
    :dismissable-mask="false"
    :style="{ width: '480px', maxWidth: 'calc(100vw - 32px)', background: '#111b30', color: '#edf3ff', border: '1px solid #563746', borderRadius: '20px' }"
    @update:visible="cancel"
  >
    <div class="roster-removal-dialog__warning">
      <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>
      <div><strong>{{ names }}</strong><p>{{ t('attendees.removeDialogWarning', { count: players.length }) }}</p></div>
    </div>
    <label v-if="refundable > 0" class="roster-removal-dialog__refund" for="refund-entry-fee">
      <Checkbox v-model="refund" binary input-id="refund-entry-fee" :disabled="busy" />
      <span><strong>{{ t('attendees.refundOption', { amount }) }}</strong><small>{{ t('attendees.refundWalletHint') }}</small></span>
    </label>
    <p v-else class="roster-removal-dialog__no-refund">{{ t('attendees.noRefundAvailable') }}</p>
    <AppAlert v-if="error" type="error" :message="error" />
    <template #footer>
      <div class="roster-removal-dialog__footer">
        <Button :label="t('common.cancel')" severity="secondary" outlined :disabled="busy" @click="cancel" />
        <Button :label="t(action === 'withdraw' ? 'attendees.confirmRemoveAction' : 'attendees.confirmDisqualifyAction')" icon="bi bi-person-x" severity="danger" :loading="busy" :disabled="busy" @click="emit('confirm', refundable > 0 && refund)" />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.roster-removal-dialog__warning { display: flex; gap: 13px; padding: 15px; border: 1px solid #66404d; border-radius: 13px; background: #34212a; }
.roster-removal-dialog__warning > i { color: #ffb4be; font-size: 22px; }
.roster-removal-dialog__warning strong { color: #fff0f3; overflow-wrap: anywhere; }
.roster-removal-dialog__warning p { margin: 5px 0 0; color: #d6b6bf; font-size: 12px; line-height: 1.5; }
.roster-removal-dialog__refund { display: flex; align-items: flex-start; gap: 11px; margin: 16px 0; padding: 14px; border: 1px solid #315c51; border-radius: 12px; background: #172e2b; cursor: pointer; }
.roster-removal-dialog__refund span { display: grid; gap: 4px; }
.roster-removal-dialog__refund strong { color: #b9f1de; font-size: 13px; }
.roster-removal-dialog__refund small, .roster-removal-dialog__no-refund { color: #91a7bd; font-size: 11px; }
.roster-removal-dialog__no-refund { margin: 16px 0; }
.roster-removal-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; width: 100%; }
</style>
