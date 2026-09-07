<script setup lang="ts">
import { computed } from 'vue'
import Step from 'primevue/step'
import StepList from 'primevue/steplist'
import Stepper from 'primevue/stepper'

export type StepProgressId = string | number

export interface StepProgressItem {
  id: StepProgressId
  label: string
  statusLabel?: string
}

const props = withDefaults(
  defineProps<{
    steps: StepProgressItem[]
    currentStep: StepProgressId | null
    completedSteps?: StepProgressId[]
    selectableSteps?: StepProgressId[]
    progressLabel?: string
    label: string
    interactive?: boolean
    disabled?: boolean
    compactOnMobile?: boolean
  }>(),
  {
    completedSteps: () => [],
    selectableSteps: () => [],
    progressLabel: '',
    interactive: false,
    disabled: false,
    compactOnMobile: true,
  },
)

const emit = defineEmits<{
  select: [id: StepProgressId]
}>()

const currentPrimeValue = computed(() => {
  const index = props.steps.findIndex((step) => step.id === props.currentStep)
  return index < 0 ? undefined : index + 1
})

function isSelectable(step: StepProgressItem) {
  if (!props.interactive || props.disabled) return false
  return props.selectableSteps.length ? props.selectableSteps.includes(step.id) : true
}

function selectStep(step: StepProgressItem) {
  if (isSelectable(step)) emit('select', step.id)
}

function handlePrimeSelection(value: StepProgressId) {
  const step = typeof value === 'number' ? props.steps[value - 1] : undefined
  if (step) selectStep(step)
}
</script>

<template>
  <nav class="app-step-progress" :aria-label="label">
    <p v-if="progressLabel" class="app-step-progress__label">{{ progressLabel }}</p>
    <Stepper
      :value="currentPrimeValue"
      class="app-step-progress__prime"
      @update:value="handlePrimeSelection"
    >
      <div class="app-step-progress__viewport">
        <StepList
          class="app-step-progress__list"
          :class="{ 'is-mobile-compact': compactOnMobile }"
        >
          <Step
            v-for="(step, index) in steps"
            :key="step.id"
            :value="index + 1"
            :disabled="!isSelectable(step)"
          >
            {{ step.label }}
            <span v-if="step.statusLabel" class="sr-only"> — {{ step.statusLabel }}</span>
          </Step>
        </StepList>
      </div>
    </Stepper>
  </nav>
</template>

<style scoped>
.app-step-progress__label {
  margin: 0 0 12px;
  color: #5ed2ff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.app-step-progress__prime,
.app-step-progress__viewport {
  width: 100%;
}

.app-step-progress__viewport {
  overflow-x: auto;
  padding: 2px 1px 8px;
}

@media (max-width: 540px) {
  .app-step-progress__list.is-mobile-compact {
    min-width: 34rem;
  }
}
</style>
