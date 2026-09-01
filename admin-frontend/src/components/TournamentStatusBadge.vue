<script setup lang="ts">
import { tournamentStateLabel } from '@/utils/adminLabels'

defineProps<{ state: string }>()

function badgeClass(state: string) {
  if (state === 'draft') return 'border-zinc-200 bg-zinc-100 text-zinc-700'
  if (state === 'open') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (state === 'active') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (state === 'finished') return 'border-zinc-900 bg-zinc-900 text-white'
  return 'border-zinc-200 bg-zinc-100 text-zinc-700'
}

</script>

<template>
  <span
    :class="[
      'shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium',
      badgeClass(state),
    ]"
  >
    {{ tournamentStateLabel(state) }}
  </span>
</template>
