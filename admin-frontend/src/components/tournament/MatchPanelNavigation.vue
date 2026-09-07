<script setup lang="ts">
import Button from 'primevue/button'
import { useI18n } from '@/i18n'
import type { MatchPanelSection } from '@/types/matchAdministration'

defineProps<{ disabled: boolean; contentId: string }>()
const selected = defineModel<MatchPanelSection>({ required: true })
const { t } = useI18n()
const sections: Array<{ value: MatchPanelSection; icon: string }> = [
  { value: 'live', icon: 'bi bi-broadcast' },
  { value: 'score', icon: 'bi bi-pencil-square' },
  { value: 'players', icon: 'bi bi-person-gear' },
  { value: 'times', icon: 'bi bi-clock' },
  { value: 'note', icon: 'bi bi-lock' },
  { value: 'history', icon: 'bi bi-clock-history' },
]
</script>

<template>
  <div class="match-navigation" role="group" :aria-label="t('matchDetails.sectionsLabel')">
    <Button
      v-for="section in sections"
      :key="section.value"
      type="button"
      :label="t(`matchDetails.sections.${section.value}`)"
      :icon="section.icon"
      :class="['match-navigation__button', selected === section.value && 'is-selected']"
      :aria-pressed="selected === section.value"
      :aria-controls="contentId"
      :data-section="section.value"
      :disabled="disabled"
      severity="secondary"
      outlined
      @click="selected = section.value"
    />
  </div>
</template>

<style scoped>
.match-navigation {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 18px;
}
.match-navigation__button {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 7px;
  min-width: 0;
  min-height: 68px;
  padding: 10px 6px;
  border: 1px solid #30425e;
  border-radius: 10px;
  background: #17243a;
  color: #b9cce4;
  font-size: 12px;
}
.match-navigation__button:not(:disabled):hover {
  background: #20334b;
  border-color: #537495;
  color: #eef6ff;
}
.match-navigation__button.is-selected {
  background: #10364b;
  border-color: #50bce6;
  color: #97e5ff;
  box-shadow: inset 0 0 0 1px #50bce625;
}
.match-navigation__button:focus-visible {
  outline: 2px solid #80dbff;
  outline-offset: 3px;
}
.match-navigation__button:disabled {
  opacity: 0.55;
}
.match-navigation__button :deep(.p-button-label) {
  white-space: normal;
  text-align: center;
}
@media (max-width: 360px) {
  .match-navigation {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
