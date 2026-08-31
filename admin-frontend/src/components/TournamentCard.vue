<script setup lang="ts">
interface Tournament {
  id: number
  name: string
  state: string // draft/open/active/finished
  creator: string | null
  participant_count: number
  starts_at: string | null
  min_players: number
  max_players: number | null
  target_points: number
  time_control: string
}
defineProps<{ tournament: Tournament }>()
function badgeClass(state: string) {
  if (state === 'draft') return 'bg-zinc-100 text-zinc-700 border-zinc-200'
  if (state === 'open') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (state === 'active') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (state === 'finished') return 'bg-zinc-900 text-white border-zinc-900'
  return 'bg-zinc-100 text-zinc-700 border-zinc-200'
}
function formatDate(s: string | null) {
  if (!s) return '—'
  try {
    const d = new Date(s)
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return s }
}
</script>
<template>
  <div class="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm transition hover:shadow">
    <div class="mb-2 flex items-start justify-between gap-2">
      <h3 class="text-base font-semibold text-black">{{ tournament.name }}</h3>
      <span :class="['rounded-full border px-2 py-0.5 text-xs font-medium', badgeClass(tournament.state)]">{{ tournament.state }}</span>
    </div>
    <div class="mb-3 space-y-1 text-xs text-zinc-600">
      <div><span class="font-medium text-zinc-700">Creator:</span> {{ tournament.creator || '—' }} • {{ tournament.participant_count }} attendees</div>
      <div><span class="font-medium text-zinc-700">Starts:</span> {{ formatDate(tournament.starts_at) }}</div>
      <div><span class="font-medium text-zinc-700">Players:</span> {{ tournament.min_players }}–{{ tournament.max_players ?? '∞' }} • {{ tournament.target_points }} pts • {{ tournament.time_control }}</div>
    </div>
    <div class="flex justify-end gap-2">
      <RouterLink :to="`/tournaments/${tournament.id}`" class="rounded border border-zinc-300 bg-white px-3 py-1 text-xs font-medium text-black hover:bg-zinc-50">View</RouterLink>
      <RouterLink :to="`/tournaments/${tournament.id}`" class="rounded bg-zinc-900 px-3 py-1 text-xs font-medium text-white hover:bg-black">Manage</RouterLink>
    </div>
  </div>
</template>
