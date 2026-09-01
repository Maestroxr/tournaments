<script setup lang="ts">
import type { TournamentFixture } from '@/types/tournamentProgress'

defineProps<{
  fixture: TournamentFixture
}>()
</script>

<template>
  <article class="rounded-lg border border-zinc-200 bg-zinc-50 p-3">
    <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
      <span class="min-w-28 flex-1 font-medium text-black">{{ fixture.player1?.name || 'TBD' }}</span>
      <div class="flex items-center gap-1" aria-label="Match score">
        <span class="w-12 text-center font-medium text-black">{{ fixture.score1 ?? '—' }}</span>
        <span class="text-zinc-400">:</span>
        <span class="w-12 text-center font-medium text-black">{{ fixture.score2 ?? '—' }}</span>
      </div>
      <span class="min-w-28 flex-1 text-right font-medium text-black">{{ fixture.player2?.name || 'TBD' }}</span>
    </div>
    <div class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-zinc-200 pt-2 text-xs">
      <span v-if="fixture.is_confirmed" class="font-medium text-emerald-700">Result confirmed</span>
      <span v-else-if="fixture.score1 != null" class="font-medium text-amber-700">Result received — awaiting confirmation</span>
      <span v-else class="text-zinc-500">Waiting for the game result</span>
      <span v-if="!fixture.is_confirmed && fixture.score1 != null" class="text-zinc-500">{{ fixture.confirmations }} of {{ fixture.required_confirmations }} confirmations</span>
    </div>
  </article>
</template>
