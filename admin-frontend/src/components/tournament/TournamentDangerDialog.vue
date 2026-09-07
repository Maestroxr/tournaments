<script setup lang="ts">
import { computed } from 'vue'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  mode: 'revert' | 'delete'
  name: string
  entryFee?: string | number | null
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t, locale } = useI18n()
const key = computed(() => props.mode === 'revert' ? 'revert' : 'delete')
const hasPaidEntryFee = computed(() => Number(props.entryFee ?? 0) > 0)
function cancel() { if (!props.busy) emit('cancel') }
</script>

<template>
  <Dialog
    :visible="true" modal append-to="self" class="tournament-danger-dialog"
    :header="t(`tournamentDanger.${key}Title`)" :dir="locale === 'he' ? 'rtl' : 'ltr'"
    :closable="!busy" :close-on-escape="!busy" :dismissable-mask="false"
    :style="{ width: '500px', maxWidth: 'calc(100vw - 32px)', background: '#111b30', color: '#edf3ff', border: '1px solid #573542', borderRadius: '20px' }"
    @update:visible="cancel"
  >
    <div class="tournament-danger-dialog__intro">
      <span aria-hidden="true"><i class="bi bi-exclamation-triangle"></i></span>
      <div>
        <h3>{{ name }}</h3>
        <p>{{ t(`tournamentDanger.${key}Warning`) }}</p>
      </div>
    </div>
    <ul class="tournament-danger-dialog__changes">
      <template v-if="mode === 'revert'">
        <li><i class="bi bi-people" aria-hidden="true"></i><span>{{ t('tournamentDanger.playersRemoved') }}</span></li>
        <li v-if="hasPaidEntryFee"><i class="bi bi-wallet2" aria-hidden="true"></i><span>{{ t('tournamentDanger.paymentsRefunded') }}</span></li>
        <li><i class="bi bi-file-earmark" aria-hidden="true"></i><span>{{ t('tournamentDanger.registrationClosed') }}</span></li>
      </template>
      <li v-else><i class="bi bi-trash3" aria-hidden="true"></i><span>{{ t('tournamentDanger.deletePermanent') }}</span></li>
    </ul>
    <AppAlert v-if="error" type="error" :message="error" />
    <template #footer>
      <div class="tournament-danger-dialog__footer">
        <Button :label="t('common.cancel')" severity="secondary" outlined :disabled="busy" autofocus @click="cancel" />
        <Button
          :label="t(`tournamentDanger.${key}Action`)"
          :icon="mode === 'revert' ? 'bi bi-arrow-counterclockwise' : 'bi bi-trash3'"
          severity="danger" :loading="busy" :disabled="busy" @click="emit('confirm')"
        />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.tournament-danger-dialog__intro { display: flex; align-items: center; gap: 14px; padding: 17px; border: 1px solid #66404d; border-radius: 14px; background: #34212a; }
.tournament-danger-dialog__intro > span { display: grid; width: 46px; height: 46px; flex: 0 0 46px; place-items: center; border-radius: 13px; background: #512b38; color: #ffb4be; font-size: 22px; }
.tournament-danger-dialog__intro h3 { margin: 0; color: #fff2f4; font-size: 17px; overflow-wrap: anywhere; }
.tournament-danger-dialog__intro p { margin: 5px 0 0; color: #d7b6c0; font-size: 12px; line-height: 1.5; }
.tournament-danger-dialog__changes { display: grid; gap: 11px; margin: 18px 0; padding: 0; list-style: none; color: #cbd8e9; font-size: 13px; }
.tournament-danger-dialog__changes li { display: flex; align-items: center; gap: 10px; }
.tournament-danger-dialog__changes i { color: #f1a5b4; }
.tournament-danger-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; width: 100%; }
@media (max-width: 480px) { .tournament-danger-dialog__footer :deep(.p-button) { flex: 1; } }
</style>
