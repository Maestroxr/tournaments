<script setup lang="ts">
import { computed } from 'vue'
import AppStepProgress from '@/components/AppStepProgress.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  state: string
  lifecycleState?: string
  participantCount: number
  minPlayers?: number
}>()
const { t } = useI18n()
const steps = [
  'draft',
  'registration',
  'registrationClosed',
  'draw',
  'ready',
  'live',
  'finished',
] as const
const currentIndex = computed(() => {
  if (props.state === 'draft') return 0
  if (props.lifecycleState === 'registration_closed') return 2
  if (props.lifecycleState === 'draw_ready') return 3
  if (props.lifecycleState === 'ready_to_start') return 4
  if (props.state === 'open') return 1
  if (props.state === 'active') return 5
  if (props.state === 'finished') return 6
  return -1
})
const currentLabel = computed(() => {
  const index = currentIndex.value
  if (index === -1) return t('tournamentProgress.unknown')
  const step = steps[index]
  return step ? t(`tournamentProgress.${step}`) : t('tournamentProgress.unknown')
})
const progressSteps = computed(() =>
  steps.map((step, index) => ({
    id: step,
    label: t(`tournamentProgress.${step}`),
    statusLabel: t(
      index === currentIndex.value
        ? 'tournamentProgress.currentStep'
        : index < currentIndex.value
          ? 'tournamentProgress.completedStep'
          : 'tournamentProgress.upcomingStep',
    ),
  })),
)
const currentStepId = computed(() => {
  const index = currentIndex.value
  return index < 0 ? null : (steps.find((_step, stepIndex) => stepIndex === index) ?? null)
})
const completedStepIds = computed(() =>
  steps.filter(
    (_step, index) =>
      index < currentIndex.value || (props.state === 'finished' && index === currentIndex.value),
  ),
)
const hint = computed(() => {
  if (props.state === 'draft') return t('tournamentProgress.draftHint')
  if (props.state === 'open' && currentIndex.value === 1 && props.minPlayers != null) {
    return t('tournamentProgress.registrationHint', {
      count: props.participantCount,
      required: props.minPlayers,
    })
  }
  if (currentIndex.value === 2) return t('tournamentProgress.registrationClosedHint')
  if (currentIndex.value === 3) return t('tournamentProgress.drawHint')
  if (currentIndex.value === 4) return t('tournamentProgress.readyHint')
  if (props.state === 'active') return t('tournamentProgress.liveHint')
  if (props.state === 'finished') return t('tournamentProgress.finishedHint')
  return ''
})
</script>

<template>
  <section class="tournament-progress" :aria-label="t('tournamentProgress.title')">
    <header class="tournament-progress__header">
      <h2>{{ t('tournamentProgress.title') }}</h2>
      <span class="tournament-progress__current" aria-live="polite">{{ currentLabel }}</span>
    </header>
    <AppStepProgress
      :steps="progressSteps"
      :current-step="currentStepId"
      :completed-steps="completedStepIds"
      :label="t('tournamentProgress.title')"
    />
    <p v-if="hint" class="tournament-progress__hint" aria-live="polite">{{ hint }}</p>
  </section>
</template>

<style scoped>
.tournament-progress {
  padding: 22px 24px;
  border: 1px solid #263653;
  border-radius: 14px;
  background: #111a30;
}
.tournament-progress__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 22px;
}
.tournament-progress__header h2 {
  margin: 0;
  color: #eef3ff;
  font-size: 14px;
  font-weight: 650;
}
.tournament-progress__current {
  border-radius: 999px;
  padding: 4px 10px;
  background: rgb(34 191 245 / 12%);
  color: #7ad9fa;
  font-size: 11px;
  font-weight: 600;
}
.tournament-progress__hint {
  margin: 20px 0 0;
  border-top: 1px solid #263653;
  padding-top: 12px;
  color: #a8b6d1;
  font-size: 12px;
  line-height: 1.6;
}
@media (max-width: 540px) {
  .tournament-progress {
    padding: 18px 12px;
  }
}
</style>
