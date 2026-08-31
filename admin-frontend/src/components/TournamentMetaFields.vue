<script setup lang="ts">
defineProps<{
  startsDate: string
  startsTime: string
  timeControl: string
  minPlayers: number
  maxPlayers: number | ''
  targetPoints: number
  errors?: Record<string, string>
}>()
defineEmits<{
  (e: 'update:startsDate', v: string): void
  (e: 'update:startsTime', v: string): void
  (e: 'update:timeControl', v: string): void
  (e: 'update:minPlayers', v: number): void
  (e: 'update:maxPlayers', v: number | ''): void
  (e: 'update:targetPoints', v: number): void
}>()
const timeOptions = ['none', 'fast', 'normal', 'slow'] as const
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Date</span>
        <input :value="startsDate" type="date" :class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.starts_at ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" @input="$emit('update:startsDate', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Time</span>
        <input :value="startsTime" type="time" :class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.starts_at ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" @input="$emit('update:startsTime', ($event.target as HTMLInputElement).value)" />
        <span v-if="errors?.starts_at" class="text-xs text-red-600">{{ errors.starts_at }}</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Time control</span>
        <select :value="timeControl" class="w-full rounded border border-zinc-300 px-3 py-2 text-sm text-black focus:border-zinc-900 focus:outline-none" @change="$emit('update:timeControl', ($event.target as HTMLSelectElement).value)">
          <option v-for="t in timeOptions" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>
    </div>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Min players</span>
        <input :value="minPlayers" type="number" min="2" :class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.min_players ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" @input="$emit('update:minPlayers', Number(($event.target as HTMLInputElement).value))" />
        <span v-if="errors?.min_players" class="text-xs text-red-600">{{ errors.min_players }}</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Max players</span>
        <input :value="maxPlayers" type="number" min="2" placeholder="unlimited" :class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.max_players ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" @input="$emit('update:maxPlayers', ($event.target as HTMLInputElement).value === '' ? '' : Number(($event.target as HTMLInputElement).value))" />
        <span v-if="errors?.max_players" class="text-xs text-red-600">{{ errors.max_players }}</span>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-black">Target points / games</span>
        <input :value="targetPoints" type="number" min="1" :class="['w-full rounded border px-3 py-2 text-sm text-black focus:outline-none', errors?.target_points ? 'border-red-500 focus:border-red-500' : 'border-zinc-300 focus:border-zinc-900']" @input="$emit('update:targetPoints', Number(($event.target as HTMLInputElement).value))" />
        <span v-if="errors?.target_points" class="text-xs text-red-600">{{ errors.target_points }}</span>
      </label>
    </div>
  </div>
</template>
