<script setup lang="ts">
import TournamentMetaItem from './TournamentMetaItem.vue'
import TournamentStatusBadge from './TournamentStatusBadge.vue'
import UserQuickView from './UserQuickView.vue'

interface Tournament {
  id: number
  name: string
  state: string // draft/open/active/finished
  creator: string | null
  creator_id: number | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
}
defineProps<{ tournament: Tournament }>()

function formatDate(s: string | null) {
  if (!s) return 'Not scheduled yet'
  try {
    const d = new Date(s)
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return s }
}

function playerRange(min: number, max: number | null) {
  return max === null ? `${min}+ players` : `${min}–${max} players`
}

function participantMessage(count: number) {
  if (count === 1) return '1 player has already registered'
  return `${count} players have already registered`
}

function primaryActionLabel(state: string) {
  return state === 'draft' ? 'Edit tournament' : 'Manage tournament'
}
</script>

<template>
  <article class="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:shadow-md">
    <div class="mb-1 flex items-start justify-between gap-3">
      <h3 class="text-lg font-semibold leading-tight text-black">{{ tournament.name }}</h3>
      <TournamentStatusBadge :state="tournament.state" />
    </div>

    <p class="mb-4 text-xs text-zinc-500">
      Created by
      <UserQuickView :user-id="tournament.creator_id" :username="tournament.creator || 'Unknown user'" />
    </p>

    <dl class="mb-4 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-zinc-50 p-3 text-sm sm:grid-cols-4">
      <TournamentMetaItem label="Starts" :value="formatDate(tournament.starts_at)" />
      <TournamentMetaItem label="Players" :value="playerRange(tournament.min_players, tournament.max_players)" />
      <TournamentMetaItem label="Match" :value="`Race to ${tournament.target_points}`" />
      <TournamentMetaItem label="Time control" :value="tournament.time_control" />
    </dl>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p class="text-sm text-zinc-600">{{ participantMessage(tournament.participant_count) }}</p>
      <RouterLink
        :to="`/tournaments/${tournament.id}${tournament.state === 'draft' ? '?edit=1' : ''}`"
        class="rounded-lg bg-zinc-900 px-4 py-2 text-center text-sm font-medium text-white hover:bg-black"
      >
        {{ primaryActionLabel(tournament.state) }}
      </RouterLink>
    </div>
  </article>
</template>
