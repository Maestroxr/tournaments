<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { MatchIncidentAction } from '@/types/matchAdministration'

type IncidentAction = MatchIncidentAction

const props = withDefaults(
  defineProps<{
    absentSince?: Partial<Record<'white' | 'black', number>>
    occurredAt?: string | null
    canRule?: boolean
    disabled?: boolean
    showActions?: boolean
  }>(),
  { canRule: undefined, disabled: false, showActions: true },
)
const emit = defineEmits<{ action: [action: IncidentAction] }>()
const { t, locale } = useI18n()
const formatter = computed(
  () => new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }),
)

function recordedTime(milliseconds: number | undefined) {
  const date = new Date(milliseconds ?? NaN)
  if (!Number.isFinite(milliseconds) || !Number.isFinite(date.getTime()) || date.getTime() <= 0)
    return { datetime: undefined, text: t('matchAdmin.incident.notRecorded') }
  return { datetime: date.toISOString(), text: formatter.value.format(date) }
}

const disconnects = computed(() =>
  (['white', 'black'] as const).map((color) => {
    const seconds = props.absentSince?.[color]
    return {
      color,
      label: t('matchAdmin.incident.recordedDisconnect', { color: t(`matchDetails.${color}`) }),
      ...recordedTime(typeof seconds === 'number' ? seconds * 1000 : undefined),
    }
  }),
)
const eventTime = computed(() =>
  recordedTime(props.occurredAt ? Date.parse(props.occurredAt) : undefined),
)
const actions: Array<{ value: IncidentAction; icon: string }> = [
  { value: 'finish', icon: 'bi-pencil-square' },
  { value: 'advance', icon: 'bi-trophy' },
  { value: 'disqualify', icon: 'bi-person-x' },
  { value: 'history', icon: 'bi-clock-history' },
]

function openAction(action: IncidentAction) {
  if (props.disabled || (action !== 'history' && props.canRule === false)) return
  emit('action', action)
}
</script>

<template>
  <div class="mt-4 grid min-w-0 gap-4" data-testid="match-adjudication">
    <div role="status" class="grid gap-2">
      <h4 class="text-base leading-6 font-semibold text-amber-100">
        {{ t('matchAdmin.incident.title') }}
      </h4>
      <p class="text-sm leading-6 text-amber-100/90">
        {{ t('matchAdmin.incident.explanation') }}
      </p>
    </div>

    <dl class="grid gap-3 border-y border-amber-200/20 py-3 text-sm min-[420px]:grid-cols-2">
      <div
        v-for="disconnect in disconnects"
        :key="disconnect.color"
        :data-absence-color="disconnect.color"
        class="grid min-w-0 gap-1"
      >
        <dt class="text-xs leading-5 text-slate-300">{{ disconnect.label }}</dt>
        <dd class="m-0 leading-6 break-words text-slate-100 tabular-nums">
          <time v-if="disconnect.datetime" :datetime="disconnect.datetime"
            ><bdi>{{ disconnect.text }}</bdi></time
          >
          <span v-else>{{ disconnect.text }}</span>
        </dd>
      </div>
      <div class="grid min-w-0 gap-1 min-[420px]:col-span-2">
        <dt class="text-xs leading-5 text-slate-300">
          {{ t('matchAdmin.incident.recordedEvent') }}
        </dt>
        <dd class="m-0 leading-6 break-words text-slate-100 tabular-nums">
          <time v-if="eventTime.datetime" :datetime="eventTime.datetime"
            ><bdi>{{ eventTime.text }}</bdi></time
          >
          <span v-else>{{ eventTime.text }}</span>
        </dd>
      </div>
    </dl>

    <p class="text-xs leading-5 text-slate-300">{{ t('matchAdmin.incident.historicalHint') }}</p>

    <div
      v-if="showActions"
      class="grid gap-2 min-[420px]:grid-cols-2"
      role="group"
      :aria-label="t('matchAdmin.incident.actionsLabel')"
    >
      <button
        v-for="item in actions"
        :key="item.value"
        type="button"
        :data-incident-action="item.value"
        class="flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm leading-5 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
        :class="
          item.value === 'finish'
            ? 'border-amber-300 bg-amber-300 text-black enabled:hover:border-amber-200 enabled:hover:bg-amber-200'
            : item.value === 'disqualify'
              ? 'border-red-300/60 bg-transparent text-red-200 enabled:hover:border-red-200 enabled:hover:bg-red-950/40'
              : 'border-amber-200/50 bg-transparent text-amber-100 enabled:hover:border-amber-200 enabled:hover:bg-amber-100/10'
        "
        :disabled="disabled || (item.value !== 'history' && canRule === false)"
        @click="openAction(item.value)"
      >
        <i :class="['bi', item.icon]" aria-hidden="true"></i>
        <span class="min-w-0 break-words">{{
          t(`matchAdmin.incident.actions.${item.value}`)
        }}</span>
      </button>
    </div>

    <p v-if="showActions && canRule === false" class="text-xs leading-5 text-slate-300">
      {{ t('matchAdmin.locked') }}
    </p>
    <p v-else-if="showActions" class="text-xs leading-5 text-slate-300">
      {{ t('matchAdmin.incident.reviewHint') }}
    </p>
  </div>
</template>
