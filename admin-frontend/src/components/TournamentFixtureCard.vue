<script setup lang="ts">
import type { TournamentFixture } from '@/types/tournamentProgress'

defineProps<{
  fixture: TournamentFixture
}>()

function resultState(fixture: TournamentFixture) {
  if (fixture.is_confirmed) {
    return { label: 'Confirmed', icon: 'bi-check-circle-fill', class: 'bg-emerald-50 text-emerald-700 ring-emerald-200' }
  }
  if (fixture.score1 != null || fixture.score2 != null) {
    return { label: 'Awaiting confirmation', icon: 'bi-hourglass-split', class: 'bg-amber-50 text-amber-800 ring-amber-200' }
  }
  return { label: 'In progress', icon: 'bi-play-circle', class: 'bg-blue-50 text-blue-700 ring-blue-200' }
}

function playerInitial(name: string | null | undefined) {
  return name?.trim().charAt(0).toUpperCase() || '?'
}
</script>

<template>
  <article class="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between gap-3">
      <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Match #{{ fixture.id }}</span>
      <span :class="['inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1', resultState(fixture).class]">
        <i :class="['bi', resultState(fixture).icon]" aria-hidden="true"></i>
        {{ resultState(fixture).label }}
      </span>
    </div>

    <div class="mt-4 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
      <div class="min-w-0 text-left">
        <span class="mb-1 inline-flex h-7 w-7 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold text-zinc-600">{{ playerInitial(fixture.player1?.name) }}</span>
        <p class="truncate text-sm font-semibold text-black">{{ fixture.player1?.name || 'Awaiting player' }}</p>
      </div>
      <div class="flex min-w-24 items-center justify-center rounded-lg bg-zinc-950 px-3 py-2 text-lg font-bold tabular-nums text-white" aria-label="Match score">
        <span>{{ fixture.score1 ?? '–' }}</span>
        <span class="px-2 text-zinc-500">:</span>
        <span>{{ fixture.score2 ?? '–' }}</span>
      </div>
      <div class="min-w-0 text-right">
        <span class="mb-1 inline-flex h-7 w-7 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold text-zinc-600">{{ playerInitial(fixture.player2?.name) }}</span>
        <p class="truncate text-sm font-semibold text-black">{{ fixture.player2?.name || 'Awaiting player' }}</p>
      </div>
    </div>

    <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-zinc-100 pt-3 text-xs">
      <span v-if="fixture.is_confirmed" class="text-zinc-500">Result is locked into the bracket</span>
      <span v-else-if="fixture.score1 != null || fixture.score2 != null" class="text-zinc-500">{{ fixture.confirmations }} of {{ fixture.required_confirmations }} confirmations received</span>
      <span v-else class="text-zinc-500">Score will appear when the game ends</span>
      <span v-if="fixture.editable && !fixture.is_confirmed" class="font-medium text-zinc-700">Admin action available</span>
    </div>
    <div v-if="fixture.live && !fixture.is_confirmed" class="mt-3 grid grid-cols-3 border-t border-zinc-100 pt-3 text-xs">
      <div><p class="text-zinc-500">Live score</p><p class="mt-0.5 font-semibold text-black">{{ fixture.live.match_score.white }} : {{ fixture.live.match_score.black }}</p></div>
      <div class="border-x border-zinc-100 px-3"><p class="text-zinc-500">Turn</p><p class="mt-0.5 font-semibold capitalize text-black">{{ fixture.live.state.turn || 'Waiting' }}</p></div>
      <div class="pl-3"><p class="text-zinc-500">Cube</p><p class="mt-0.5 font-semibold text-black">{{ fixture.live.state.cube || 1 }}</p></div>
    </div>
  </article>
</template>
