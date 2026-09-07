<script setup lang="ts">
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'
defineProps<{ busy: boolean; disabled: boolean; unchanged: boolean; inputId: string }>()
const note = defineModel<string>({ required: true })
const emit = defineEmits<{ save: [] }>()
const { t } = useI18n()
</script>
<template>
  <section class="note">
    <label :for="inputId"
      ><i class="bi bi-lock" aria-hidden="true"></i> {{ t('matchAdmin.note') }}</label
    >
    <small>{{ t('matchAdmin.private') }}</small>
    <Textarea
      :id="inputId"
      v-model="note"
      rows="3"
      maxlength="5000"
      :disabled="busy"
      :placeholder="t('matchAdmin.notePlaceholder')"
    />
    <Button
      :label="t('matchAdmin.saveNote')"
      size="small"
      severity="secondary"
      outlined
      :loading="busy"
      :disabled="busy || disabled || unchanged"
      @click="emit('save')"
    />
  </section>
</template>
<style scoped>
.note {
  display: grid;
  gap: 9px;
  padding: 16px;
  border: 1px solid #2b3e5e;
  border-radius: 12px;
}
label {
  font-size: 14px;
  font-weight: 600;
}
small {
  color: #9fb3ce;
  font-size: 11px;
}
textarea {
  width: 100%;
  background: #0e1729;
  color: #edf3ff;
  border: 1px solid #36516f;
  border-radius: 7px;
  padding: 10px;
  resize: vertical;
}
button {
  justify-self: start;
}
</style>
