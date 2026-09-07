<script setup lang="ts">
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'

const props = defineProps<{ name: string; participantCount: number; busy?: boolean; error?: string }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t, locale } = useI18n()
function cancel() { if (!props.busy) emit('cancel') }
function confirm() { if (!props.busy) emit('confirm') }
</script>

<template>
  <Dialog
    :visible="true" modal append-to="self" class="start-tournament-dialog"
    :header="t('tournamentActions.startDialogTitle')"
    :dir="locale === 'he' ? 'rtl' : 'ltr'"
    :closable="!busy" :close-on-escape="!busy" :dismissable-mask="false"
    :style="{ width: '480px', maxWidth: 'calc(100vw - 32px)', background: '#111b30', color: '#edf3ff', border: '1px solid #2b3e5e', borderRadius: '20px' }"
    @update:visible="cancel"
  >
    <div class="start-tournament-dialog__intro">
      <span class="start-tournament-dialog__icon" aria-hidden="true"><i class="bi bi-trophy"></i></span>
      <div>
        <h3>{{ name }}</h3>
        <p>{{ t('tournamentActions.startPlayerCount', { count: participantCount }) }}</p>
      </div>
    </div>
    <p class="start-tournament-dialog__hint">{{ t('tournamentActions.startDialogHint') }}</p>
    <ul class="start-tournament-dialog__changes">
      <li><i class="bi bi-lock" aria-hidden="true"></i><span>{{ t('tournamentActions.registrationWillClose') }}</span></li>
      <li><i class="bi bi-diagram-3" aria-hidden="true"></i><span>{{ t('tournamentActions.pairingsWillBeCreated') }}</span></li>
    </ul>
    <p v-if="error" role="alert" class="start-tournament-dialog__error">{{ error }}</p>
    <template #footer>
      <div class="start-tournament-dialog__footer">
        <Button :label="t('common.cancel')" severity="secondary" outlined :disabled="busy" autofocus @click="cancel" />
        <Button :label="t('tournamentActions.start')" icon="bi bi-play-fill" severity="success" :loading="busy" :disabled="busy" @click="confirm" />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.start-tournament-dialog__intro { display: flex; align-items: center; gap: 14px; padding: 18px; border: 1px solid #2b3e5e; border-radius: 14px; background: #17253d; }
.start-tournament-dialog__icon { display: grid; place-items: center; flex: 0 0 46px; height: 46px; border-radius: 14px; background: #163e3c; color: #79e1c1; font-size: 23px; }
.start-tournament-dialog__intro h3 { margin: 0; color: #f2f6ff; font-size: 18px; font-weight: 650; overflow-wrap: anywhere; }
.start-tournament-dialog__intro p { margin: 5px 0 0; color: #a9bdd9; font-size: 13px; }
.start-tournament-dialog__hint { margin: 20px 0 12px; color: #c3d0e5; font-size: 14px; line-height: 1.6; }
.start-tournament-dialog__changes { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; color: #d4e0f2; font-size: 14px; }
.start-tournament-dialog__changes li { display: flex; align-items: center; gap: 10px; }
.start-tournament-dialog__changes i { color: #79d4ff; }
.start-tournament-dialog__error { margin-top: 16px; padding: 12px; border-radius: 10px; background: #3a202a; color: #ffb4be; font-size: 13px; }
.start-tournament-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; width: 100%; padding-top: 8px; }
@media (max-width: 480px) { .start-tournament-dialog__footer :deep(.p-button) { flex: 1; } }
</style>
