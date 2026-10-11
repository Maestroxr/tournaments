<script setup lang="ts" generic="R extends GameModeRules">
import { computed } from 'vue'
import type { GameModeRules } from '@/types/directPlay'
import { useI18n } from '@/i18n'
import AdminChoiceGroup from './AdminChoiceGroup.vue'
const rules = defineModel<R>({ required: true })
const props = defineProps<{ error?: string; targetOptions?: number[] }>()
const { t } = useI18n()
const points = computed(() =>
  (props.targetOptions ?? Array.from({ length: 25 }, (_, i) => i + 1)).map((value) => ({
    value,
    label: String(value),
  })),
)
const clocks = computed(() =>
  ['none', 'normal', 'fast', 'slow'].map((value) => ({
    value,
    label: t('directPlay.ruleClocks.' + value),
  })),
)
const cubes = computed(() =>
  [true, false].map((value) => ({
    value,
    label: t(value ? 'directPlay.ruleWithDoubling' : 'directPlay.ruleWithoutDoubling'),
  })),
)
</script>
<template>
  <div class="grid gap-6 xl:grid-cols-2">
    <AdminChoiceGroup
      v-model="rules.target_points"
      :options="points"
      :label="t('directPlay.allowedPoints')"
    />
    <AdminChoiceGroup
      v-model="rules.time_controls"
      :options="clocks"
      :label="t('gameSettings.playerClocks')"
    />
    <AdminChoiceGroup
      v-model="rules.doubling_options"
      :options="cubes"
      :label="t('directPlay.allowedDoubling')"
    />
  </div>
  <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
</template>
