<script setup lang="ts">
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  tournamentName: string
  busy?: boolean
  error?: string
}>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t, locale } = useI18n()

function cancel() {
  if (!props.busy) emit('cancel')
}
</script>

<template>
  <Dialog
    :visible="true"
    modal
    append-to="self"
    class="results-confirm-dialog"
    :header="t('tournamentResults.confirmAction')"
    :dir="locale === 'he' ? 'rtl' : 'ltr'"
    :closable="!busy"
    :close-on-escape="!busy"
    :dismissable-mask="false"
    :style="{
      width: '500px',
      maxWidth: 'calc(100vw - 32px)',
      background: '#111b30',
      color: '#edf3ff',
      border: '1px solid #2b4f58',
      borderRadius: '20px',
    }"
    @update:visible="cancel"
  >
    <div class="results-confirm-dialog__intro">
      <span class="results-confirm-dialog__icon" aria-hidden="true">
        <i class="bi bi-check2-circle"></i>
      </span>
      <div>
        <h3>{{ tournamentName }}</h3>
        <p>{{ t('tournamentResults.ready') }}</p>
      </div>
    </div>

    <p class="results-confirm-dialog__prompt">{{ t('tournamentResults.confirmPrompt') }}</p>
    <div class="results-confirm-dialog__notice">
      <i class="bi bi-eye" aria-hidden="true"></i>
      <span>{{ t('tournamentResults.readyHint') }}</span>
    </div>
    <AppAlert v-if="error" type="error" :message="error" />

    <template #footer>
      <div class="results-confirm-dialog__footer">
        <Button
          :label="t('common.cancel')"
          severity="secondary"
          outlined
          :disabled="busy"
          autofocus
          @click="cancel"
        />
        <Button
          :label="t('tournamentResults.confirmAction')"
          icon="bi bi-check2-circle"
          severity="success"
          :loading="busy"
          :disabled="busy"
          @click="emit('confirm')"
        />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.results-confirm-dialog__intro {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 17px;
  border: 1px solid #2d5360;
  border-radius: 14px;
  background: #142b38;
}
.results-confirm-dialog__icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  border-radius: 14px;
  background: #163e3c;
  color: #79e1c1;
  font-size: 23px;
  place-items: center;
}
.results-confirm-dialog__intro h3 {
  margin: 0;
  overflow-wrap: anywhere;
  color: #f2f6ff;
  font-size: 17px;
  font-weight: 700;
}
.results-confirm-dialog__intro p {
  margin: 5px 0 0;
  color: #9fc8c9;
  font-size: 12px;
}
.results-confirm-dialog__prompt {
  margin: 20px 0 14px;
  color: #d6e2f3;
  font-size: 14px;
  line-height: 1.6;
}
.results-confirm-dialog__notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 18px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #17253d;
  color: #aebed5;
  font-size: 12px;
  line-height: 1.5;
}
.results-confirm-dialog__notice i { margin-top: 1px; color: #79d4ff; }
.results-confirm-dialog__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  width: 100%;
}
@media (max-width: 480px) {
  .results-confirm-dialog__footer :deep(.p-button) { flex: 1; }
}
</style>
