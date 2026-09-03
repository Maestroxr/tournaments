<script setup lang="ts">
import TournamentMetaItem from './TournamentMetaItem.vue'
import TournamentStatusBadge from './TournamentStatusBadge.vue'
import UserQuickView from './UserQuickView.vue'
import { timeControlLabel } from '@/utils/adminLabels'
import { useI18n } from '@/i18n'

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
  doubling_enabled: boolean
  entry_fee: string
  prize_money: string
}
defineProps<{ tournament: Tournament }>()
const { t } = useI18n()

function formatDate(s: string | null) {
  if (!s) return t('tournaments.notScheduledYet')
  try {
    const d = new Date(s)
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return s }
}

function playerRange(min: number, max: number | null) {
  return max === null ? t('tournaments.playersPlus', { count: min }) : t('tournaments.playersRange', { min, max })
}

function participantMessage(count: number) {
  if (count === 1) return t('tournaments.registeredOne')
  return t('tournaments.registeredMany', { count })
}

function participantProgress(count: number, max: number | null) {
  const target = max ?? Math.max(count, 1)
  return `${Math.min((count / target) * 100, 100)}%`
}

function scheduleLabel(startsAt: string | null) {
  return startsAt ? t('tournaments.scheduledStart') : t('tournaments.startTime')
}

function primaryActionLabel(state: string) {
  return state === 'draft' ? t('tournaments.editTournament') : t('tournaments.manageTournament')
}

function primaryActionTo(tournament: Tournament) {
  return `/tournaments/${tournament.id}${tournament.state === 'draft' ? '?edit=1' : ''}`
}
</script>

<template>
  <article
    class="group flex h-full flex-col rounded-lg border border-zinc-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="mb-1 text-xs font-medium tracking-wide text-zinc-400 uppercase">
          {{ t('tournaments.tournamentNumber', { id: tournament.id }) }}
        </p>
        <h3 class="truncate text-lg font-semibold leading-tight text-zinc-950">{{ tournament.name }}</h3>
      </div>
      <TournamentStatusBadge :state="tournament.state" />
    </div>

    <p class="mt-2 text-xs text-zinc-500">
      {{ t('tournaments.createdBy') }}
      <UserQuickView
        :user-id="tournament.creator_id"
        :username="tournament.creator || t('tournaments.unknownUser')"
      />
    </p>

    <section class="mt-5 rounded-lg border border-zinc-200 bg-zinc-50 p-4">
      <div class="flex items-start gap-3">
        <i class="bi bi-calendar3 mt-0.5 text-base text-zinc-400" aria-hidden="true"></i>
        <div class="min-w-0">
          <p class="text-xs font-medium text-zinc-500">{{ scheduleLabel(tournament.starts_at) }}</p>
          <p class="mt-0.5 truncate text-sm font-semibold text-zinc-900">
            {{ formatDate(tournament.starts_at) }}
          </p>
        </div>
      </div>

      <div class="mt-4 border-t border-zinc-200 pt-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-xs font-medium text-zinc-500">{{ t('tournaments.registration') }}</p>
            <p class="mt-0.5 text-sm font-semibold text-zinc-900">
              {{ tournament.participant_count }} / {{ tournament.max_players ?? t('tournaments.unlimited') }} {{ t('nav.users').toLowerCase() }}
            </p>
          </div>
          <span class="rounded-md bg-white px-2 py-1 text-xs font-medium text-zinc-600 ring-1 ring-zinc-200">
            {{ t('tournaments.minPlayersShort', { count: tournament.min_players }) }}
          </span>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-200" aria-hidden="true">
          <div
            class="h-full rounded-full bg-emerald-500 transition-[width]"
            :style="{ width: participantProgress(tournament.participant_count, tournament.max_players) }"
          ></div>
        </div>
      </div>
    </section>

    <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 text-sm">
      <TournamentMetaItem :label="t('tournaments.matchFormat')" :value="t('tournaments.raceTo', { points: tournament.target_points })" />
      <TournamentMetaItem :label="t('tournaments.timeControl')" :value="timeControlLabel(tournament.time_control)" />
      <TournamentMetaItem
        :label="t('tournaments.doublingCube')"
        :value="tournament.doubling_enabled ? t('common.enabled') : t('common.disabled')"
      />
      <TournamentMetaItem :label="t('tournaments.capacity')" :value="playerRange(tournament.min_players, tournament.max_players)" />
    </dl>

    <section class="mt-5 grid grid-cols-2 divide-x divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
      <div class="px-4 py-3">
        <p class="text-xs font-medium text-zinc-500">{{ t('tournaments.entryFee') }}</p>
        <p class="mt-1 text-base font-semibold tabular-nums text-zinc-900">
          ${{ Number(tournament.entry_fee || 0).toFixed(2) }}
        </p>
      </div>
      <div class="px-4 py-3">
        <p class="text-xs font-medium text-zinc-500">{{ t('tournaments.prizePool') }}</p>
        <p class="mt-1 text-base font-semibold tabular-nums text-emerald-700">
          ${{ Number(tournament.prize_money || 0).toFixed(2) }}
        </p>
      </div>
    </section>

    <div class="mt-5 flex flex-col gap-3 border-t border-zinc-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
      <p class="text-sm text-zinc-600">{{ participantMessage(tournament.participant_count) }}</p>
      <RouterLink
        :to="primaryActionTo(tournament)"
        class="inline-flex items-center justify-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-black focus-visible:ring-2 focus-visible:ring-zinc-900 focus-visible:ring-offset-2"
      >
        {{ primaryActionLabel(tournament.state) }}
        <i class="bi bi-arrow-right" aria-hidden="true"></i>
      </RouterLink>
    </div>
  </article>
</template>
