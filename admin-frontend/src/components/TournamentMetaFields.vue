<script setup lang="ts">
import { computed } from 'vue'
import DatePicker from 'primevue/datepicker'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'

const props = defineProps<{
  startsDate?: string
  startsTime?: string
  timeControl?: string
  minPlayers?: number
  maxPlayers?: number | ''
  targetPoints?: number
  doublingEnabled?: boolean
  entryFee?: number
  prizeMoney?: number
  minStartsDate?: string
  minStartsTime?: string
  rulesOnly?: boolean
  errors?: Record<string, string>
}>()
const emit = defineEmits<{
  (e: 'update:startsDate', v: string): void
  (e: 'update:startsTime', v: string): void
  (e: 'update:timeControl', v: string): void
  (e: 'update:minPlayers', v: number): void
  (e: 'update:maxPlayers', v: number | ''): void
  (e: 'update:targetPoints', v: number): void
  (e: 'update:doublingEnabled', v: boolean): void
  (e: 'update:entryFee', v: number): void
  (e: 'update:prizeMoney', v: number): void
}>()
const timeOptions = [
  { value: 'none', label: 'No clock', detail: 'Untimed match' },
  { value: 'fast', label: 'Fast', detail: '5 minutes per player' },
  { value: 'normal', label: 'Normal', detail: '10 minutes per player' },
  { value: 'slow', label: 'Slow', detail: '20 minutes per player' },
]
const pad = (value: number) => String(value).padStart(2, '0')
const dateInputValue = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const timeInputValue = (date: Date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`
const parseLocalDate = (value?: string) => {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  return year && month && day ? new Date(year, month - 1, day) : null
}
const parseLocalTime = (value?: string) => {
  if (!value) return null
  const parts = value.split(':').map(Number)
  const hours = parts[0] ?? Number.NaN
  const minutes = parts[1] ?? Number.NaN
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return date
}
const minStartsDateObject = computed(() => parseLocalDate(props.minStartsDate) || undefined)
const minStartsTimeObject = computed(() => parseLocalTime(props.minStartsTime) || undefined)
const startsDateObject = computed<Date | null>({
  get: () => parseLocalDate(props.startsDate),
  set: (value) => emit('update:startsDate', value ? dateInputValue(value) : ''),
})
const startsTimeObject = computed<Date | null>({
  get: () => parseLocalTime(props.startsTime),
  set: (value) => emit('update:startsTime', value ? timeInputValue(value) : ''),
})
</script>

<template>
  <div class="space-y-4">
    <div v-if="!rulesOnly" class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Date</span>
        <DatePicker v-model="startsDateObject" date-format="yy-mm-dd" show-icon fluid manual-input :min-date="minStartsDateObject" :input-class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.starts_at ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" />
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Time</span>
        <DatePicker v-model="startsTimeObject" time-only hour-format="24" show-icon fluid manual-input :min-date="minStartsTimeObject" :input-class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.starts_at ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" />
        <span v-if="errors?.starts_at" class="text-xs text-red-600">{{ errors.starts_at }}</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Time control</span>
        <Select :model-value="timeControl" :options="timeOptions" option-label="label" option-value="value" fluid @update:model-value="emit('update:timeControl', String($event))" />
      </label>
    </div>

    <div :class="['grid grid-cols-1 gap-4', rulesOnly ? 'sm:grid-cols-2' : 'sm:grid-cols-3']">
      <label v-if="!rulesOnly" class="block">
        <span class="mb-1 block text-sm font-medium text-black">Min players</span>
        <InputNumber :model-value="minPlayers" :min="2" show-buttons fluid :invalid="Boolean(errors?.min_players)" @update:model-value="emit('update:minPlayers', Number($event ?? 0))" />
        <span v-if="errors?.min_players" class="text-xs text-red-600">{{ errors.min_players }}</span>
      </label>
      <label v-if="!rulesOnly" class="block">
        <span class="mb-1 block text-sm font-medium text-black">Max players</span>
        <InputNumber :model-value="maxPlayers === '' ? null : maxPlayers" :min="2" placeholder="unlimited" show-buttons fluid :invalid="Boolean(errors?.max_players)" @update:model-value="emit('update:maxPlayers', $event === null ? '' : Number($event))" />
        <span v-if="errors?.max_players" class="text-xs text-red-600">{{ errors.max_players }}</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Match length — race to</span>
        <InputNumber :model-value="targetPoints" :min="1" show-buttons fluid :invalid="Boolean(errors?.target_points)" @update:model-value="emit('update:targetPoints', Number($event ?? 0))" />
        <span v-if="errors?.target_points" class="text-xs text-red-600">{{ errors.target_points }}</span>
        <span v-else class="text-xs text-zinc-500">The first player to reach this score wins the match.</span>
      </label>
      <label v-if="rulesOnly" class="block">
        <span class="mb-1 block text-sm font-medium text-black">Clock setting</span>
        <Select :model-value="timeControl" :options="timeOptions" option-label="label" option-value="value" fluid @update:model-value="emit('update:timeControl', String($event))" />
        <span class="text-xs text-zinc-500">Time allowance shown for each player.</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Entry fee</span>
        <InputNumber :model-value="entryFee" :min="0" :min-fraction-digits="2" :max-fraction-digits="2" fluid :invalid="Boolean(errors?.entry_fee)" @update:model-value="emit('update:entryFee', Number($event ?? 0))" />
        <span v-if="errors?.entry_fee" class="text-xs text-red-600">{{ errors.entry_fee }}</span>
        <span v-else class="text-xs text-zinc-500">Players need this balance to register.</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Prize</span>
        <InputNumber :model-value="prizeMoney" :min="0" :min-fraction-digits="2" :max-fraction-digits="2" fluid :invalid="Boolean(errors?.prize_money)" @update:model-value="emit('update:prizeMoney', Number($event ?? 0))" />
        <span v-if="errors?.prize_money" class="text-xs text-red-600">{{ errors.prize_money }}</span>
        <span v-else class="text-xs text-zinc-500">Prize pool shown to players.</span>
      </label>
      <label class="flex items-start gap-3 rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
        <ToggleSwitch :model-value="doublingEnabled" class="mt-0.5" @update:model-value="emit('update:doublingEnabled', Boolean($event))" />
        <span>
          <span class="block text-sm font-medium text-black">Doubling cube</span>
          <span class="text-xs text-zinc-500">Allow players to offer doubles during tournament matches.</span>
        </span>
      </label>
    </div>
  </div>
</template>
