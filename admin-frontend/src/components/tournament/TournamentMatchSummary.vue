<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'
const props = defineProps<{
  fixtures: TournamentFixture[]
  players: number
  controlRoom?: TournamentProgressData['control_room']
}>()
const { t } = useI18n()
const statusCount = (status: TournamentFixture['operational_status']) => props.controlRoom?.counts[status!] ?? props.fixtures.filter(f => {
  if (status === 'completed') return f.is_confirmed
  if (status === 'review') return !f.is_confirmed && (f.score1 != null || f.score2 != null || f.confirmations > 0)
  if (status === 'playing') return !f.is_confirmed && f.live?.status === 'playing'
  if (status === 'waiting') return !f.is_confirmed && !f.live && f.score1 == null && f.score2 == null && Boolean(f.player1 && f.player2)
  if (status === 'waiting_opponent') return !f.is_confirmed && Boolean(f.player1 || f.player2) && !(f.player1 && f.player2)
  return f.operational_status === status
}).length
const attentionCount = computed(() => statusCount('stalled') + statusCount('review'))
const stats = computed(() => [
  { key: 'players', value: props.players, icon: 'bi-people' },
  { key: 'playing', value: statusCount('playing'), icon: 'bi-play-circle' },
  { key: 'waiting', value: statusCount('waiting') + statusCount('waiting_opponent'), icon: 'bi-hourglass-split' },
  { key: 'attention', value: attentionCount.value, icon: 'bi-exclamation-diamond' },
  { key: 'completed', value: statusCount('completed'), icon: 'bi-check-circle' },
])
const roundProgress = computed(() => {
  const total = props.controlRoom?.round_total ?? 0
  const complete = props.controlRoom?.round_completed ?? 0
  return { total, complete, percentage: total ? Math.round((complete / total) * 100) : 0 }
})
</script>

<template>
  <section class="match-summary-wrap">
    <div v-if="controlRoom" class="round-progress">
      <div>
        <p>{{ t('controlRoom.currentRound') }}</p>
        <strong>{{ controlRoom.current_stage }} · {{ controlRoom.current_round }}</strong>
      </div>
      <div class="round-progress__count">
        <span>{{ t('controlRoom.roundProgress', { complete: roundProgress.complete, total: roundProgress.total }) }}</span>
        <strong>{{ roundProgress.percentage }}%</strong>
      </div>
      <div class="round-progress__track"><span :style="{ width: `${roundProgress.percentage}%` }"></span></div>
    </div>
    <dl class="match-summary">
      <div v-for="stat in stats" :key="stat.key" :class="['match-summary__item', stat.key === 'attention' && stat.value && 'is-attention']">
        <dt><i :class="['bi', stat.icon]" aria-hidden="true"></i>{{ t(`controlRoom.${stat.key}`) }}</dt>
        <dd>{{ stat.value }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.match-summary-wrap { display: grid; gap: 12px; }
.round-progress { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 10px 20px; padding: 16px 18px; border: 1px solid #2b4968; border-radius: 12px; background: linear-gradient(135deg, #152942, #132138); }
.round-progress p { margin: 0 0 4px; color: #79cfee; font-size: 10px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.round-progress strong { color: #eef7ff; font-size: 14px; }
.round-progress__count { display: flex; align-items: center; gap: 12px; color: #9db0ca; font-size: 11px; }
.round-progress__count strong { color: #8be0c6; font-size: 14px; font-variant-numeric: tabular-nums; }
.round-progress__track { grid-column: 1 / -1; overflow: hidden; height: 5px; border-radius: 999px; background: #253852; }
.round-progress__track span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #3f9dd0, #55d0ab); transition: width .25s ease; }
.match-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.match-summary__item { padding: 18px; border: 1px solid #293a57; border-radius: 12px; background: #152138; }
.match-summary__item.is-attention { border-color: #684c30; background: #251f22; }
.match-summary dt { display: flex; align-items: center; gap: 8px; color: #aebfd8; font-size: 12px; }
.match-summary dt i { color: #7ad6ff; }
.match-summary__item.is-attention dt i { color: #efbd68; }
.match-summary dd { margin: 10px 0 0; color: #eef5ff; font-size: 28px; line-height: 1; font-weight: 700; }
@media (max-width: 800px) { .match-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .round-progress { grid-template-columns: 1fr; } .round-progress__count { justify-content: space-between; } }
</style>
