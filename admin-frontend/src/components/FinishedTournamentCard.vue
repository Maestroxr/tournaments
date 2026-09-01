<script setup lang="ts">
import TournamentMetaItem from './TournamentMetaItem.vue'
import TournamentStatusBadge from './TournamentStatusBadge.vue'
import UserQuickView from './UserQuickView.vue'
import { timeControlLabel } from '@/utils/adminLabels'

interface PodiumPlayer {
  id: number | string
  name: string
  position: number
}

interface Tournament {
  id: number
  name: string
  state: string
  creator: string | null
  creator_id: number | null
  participant_count: number
  starts_at: string | null
  target_points: number
  time_control: string
  doubling_enabled: boolean
  entry_fee: string
  prize_money: string
  champion?: PodiumPlayer | null
  podium?: PodiumPlayer[]
}

defineProps<{ tournament: Tournament }>()

function formatDate(s: string | null) {
  if (!s) return 'Not scheduled'
  try {
    return new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return s
  }
}

function medalLabel(position: number) {
  if (position === 0) return 'Winner'
  if (position === 1) return 'Runner-up'
  if (position === 2) return 'Third place'
  return `Place ${position + 1}`
}
</script>

<template>
  <article class="rounded-lg border border-emerald-200 bg-white p-5 shadow-sm transition hover:shadow-md">
    <div class="mb-5 flex items-start justify-between gap-3">
      <div>
        <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Tournament #{{ tournament.id }}</p>
        <h3 class="text-lg font-semibold leading-tight text-black">{{ tournament.name }}</h3>
        <p class="mt-1 text-xs text-zinc-500">
          Created by
          <UserQuickView
            :user-id="tournament.creator_id"
            :username="tournament.creator || 'Unknown user'"
          />
        </p>
      </div>
      <TournamentStatusBadge :state="tournament.state" />
    </div>

    <div class="mb-5 flex items-center gap-3 border-y border-emerald-100 bg-emerald-50 px-3 py-3">
      <span class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-800"><i class="bi bi-trophy-fill" aria-hidden="true"></i></span>
      <div class="min-w-0">
        <p class="text-xs font-semibold tracking-wide text-emerald-700 uppercase">Champion</p>
        <p class="truncate text-lg font-bold text-black">
          {{ tournament.champion?.name || tournament.podium?.[0]?.name || 'Not recorded' }}
        </p>
      </div>
    </div>

    <ol v-if="tournament.podium?.length" class="mb-5 divide-y divide-zinc-100 border-y border-zinc-100">
      <li
        v-for="player in tournament.podium.slice(0, 3)"
        :key="player.id"
        class="flex items-center justify-between gap-3 py-2.5 text-sm"
      >
        <span class="flex min-w-0 items-center gap-2 font-medium text-black">
          <span class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold text-zinc-600">{{ player.position + 1 }}</span>
          <span class="truncate">{{ player.name }}</span>
        </span>
        <span class="shrink-0 text-xs text-zinc-500">{{ medalLabel(player.position) }}</span>
      </li>
    </ol>

    <dl class="mb-5 grid grid-cols-2 gap-x-4 gap-y-3 border-y border-zinc-100 py-3 text-sm">
      <TournamentMetaItem label="Finished from" :value="formatDate(tournament.starts_at)" />
      <TournamentMetaItem label="Players" :value="String(tournament.participant_count)" />
      <TournamentMetaItem label="Match" :value="`Race to ${tournament.target_points}`" />
      <TournamentMetaItem label="Time control" :value="timeControlLabel(tournament.time_control)" />
      <TournamentMetaItem label="Doubling" :value="tournament.doubling_enabled ? 'Enabled' : 'Disabled'" />
      <TournamentMetaItem label="Entry fee" :value="Number(tournament.entry_fee || 0).toFixed(2)" />
      <TournamentMetaItem label="Prize" :value="Number(tournament.prize_money || 0).toFixed(2)" />
    </dl>

    <RouterLink :to="`/tournaments/${tournament.id}/progress`" class="flex items-center justify-between rounded-lg bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-black">
      <span>Open full results</span>
      <i class="bi bi-arrow-right" aria-hidden="true"></i>
    </RouterLink>
  </article>
</template>
