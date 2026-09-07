<script setup lang="ts">
import { computed } from 'vue'
import type { TournamentFixture } from '@/types/tournamentProgress'
import { useI18n } from '@/i18n'
const props = defineProps<{ fixture: TournamentFixture; sources?: Partial<Record<1 | 2, TournamentFixture>> }>()
const emit = defineEmits<{ select: [id: number] }>()
const { t, direction } = useI18n()
const state = computed(() => props.fixture.is_confirmed ? 'completed'
  : props.fixture.score1 != null || props.fixture.score2 != null ? 'confirming'
  : props.fixture.live?.status === 'playing' ? 'playing' : 'waiting')
const labels = { completed: 'tournaments.confirmed', confirming: 'tournaments.awaitingConfirmation', playing: 'tournaments.inProgress', waiting: 'tournaments.waiting' }
const statusLabel = computed(() => props.fixture.admin_resolution === 'disqualify' ? 'matchAdmin.disqualifiedStatus'
  : props.fixture.admin_resolution === 'advance' ? 'matchAdmin.advancedStatus' : labels[state.value])
const rows = computed(() => ([1, 2] as const).map(slot => {
  const player = slot === 1 ? props.fixture.player1 : props.fixture.player2
  const score = slot === 1 ? props.fixture.score1 : props.fixture.score2
  const other = slot === 1 ? props.fixture.score2 : props.fixture.score1
  const source = props.sources?.[slot]
  return { slot, name: player?.name || (source ? t('tournamentBracket.winnerOf', { id: source.id }) : t('tournaments.awaitingPlayer')),
    score, waiting: !player, winner: props.fixture.is_confirmed && (props.fixture.winner_id != null
      ? props.fixture.winner_id === player?.id : score != null && other != null && score > other) }
}))
</script>

<template>
  <article :class="['bracket-match', `bracket-match--${state}`]" :dir="direction" :aria-label="t('tournaments.matchNumber', { id: fixture.id })">
    <header>
      <span>#{{ fixture.id }}</span>
      <span class="bracket-match__status"><i aria-hidden="true"></i>{{ t(statusLabel) }}</span>
    </header>
    <div v-for="row in rows" :key="row.slot" :class="['bracket-match__player', row.winner && 'is-winner', row.waiting && 'is-waiting']">
      <i v-if="row.winner" class="bi bi-check-circle-fill" aria-hidden="true"></i>
      <span :title="row.name">{{ row.name }}</span>
      <strong>{{ row.score ?? '–' }}</strong>
    </div>
    <button type="button" class="bracket-match__open" aria-haspopup="dialog"
      :aria-label="t('matchDetails.open', { id: fixture.id })" @click="emit('select', fixture.id)"></button>
  </article>
</template>

<style scoped>
.bracket-match { position: relative; height: 62px; box-sizing: border-box; border: 1px solid #40516b; border-radius: 4px; background: #1c2a40; color: #e9f1ff; }
.bracket-match header { position: absolute; inset-inline: 0; top: -21px; height: 17px; display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #91a5c2; font-size: 10px; }
.bracket-match__status { display: flex; align-items: center; gap: 5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.bracket-match__status i { flex: 0 0 5px; height: 5px; border-radius: 50%; background: currentColor; }
.bracket-match__player { height: 30px; display: flex; align-items: center; gap: 6px; padding-inline-start: 9px; font-size: 12px; }
.bracket-match__player + .bracket-match__player { border-top: 1px solid #263651; }
.bracket-match__player span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bracket-match__player strong { display: grid; place-items: center; align-self: stretch; min-width: 30px; border-inline-start: 1px solid #40516b; background: #ffffff06; text-align: center; font-variant-numeric: tabular-nums; }
.bracket-match__player.is-waiting { color: #97aac6; font-size: 11px; }
.bracket-match__player.is-winner { background: #153d38; color: #8ae9c9; }
.bracket-match--playing { border-color: #4ab6e4; }
.bracket-match--playing .bracket-match__status { color: #78d7ff; }
.bracket-match--completed .bracket-match__status { color: #85e1bd; }
.bracket-match--confirming .bracket-match__status { color: #ebd38e; }
.bracket-match__open { position: absolute; inset: 0; width: 100%; height: 100%; padding: 0; border: 0; border-radius: inherit; background: transparent; cursor: pointer; }
.bracket-match__open:hover { background: #7bd4ff12; }
.bracket-match__open:focus-visible { outline: 2px solid #7bd4ff; outline-offset: 3px; }
</style>
