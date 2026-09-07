<script setup lang="ts">
import Button from 'primevue/button'
import UserQuickView from '@/components/UserQuickView.vue'
import { useI18n } from '@/i18n'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'

defineProps<{
  stalled: TournamentFixture[]
  review: TournamentFixture[]
  waitingPlayers: NonNullable<TournamentProgressData['control_room']>['waiting_players']
}>()
const emit = defineEmits<{ select: [fixtureId: number] }>()
const { t } = useI18n()
</script>

<template>
  <section v-if="stalled.length || review.length || waitingPlayers.length" class="live-attention" aria-labelledby="live-attention-title">
    <header>
      <div>
        <p>{{ t('controlRoom.operatorAttention') }}</p>
        <h3 id="live-attention-title">{{ t('controlRoom.needsAttention') }}</h3>
      </div>
      <span>{{ stalled.length + review.length + waitingPlayers.length }}</span>
    </header>
    <div class="live-attention__items">
      <article v-for="fixture in stalled" :key="`stalled-${fixture.id}`" class="attention-item attention-item--critical">
        <i class="bi bi-exclamation-octagon" aria-hidden="true"></i>
        <div><strong>{{ t('controlRoom.stalledMatch', { id: fixture.id }) }}</strong><p>{{ t('controlRoom.stalledMatchHint', { round: fixture.round_name || '' }) }}</p></div>
        <Button size="small" :label="t('controlRoom.inspectMatch')" severity="danger" outlined @click="emit('select', fixture.id)" />
      </article>
      <article v-for="fixture in review" :key="`review-${fixture.id}`" class="attention-item attention-item--warning">
        <i class="bi bi-clipboard-check" aria-hidden="true"></i>
        <div><strong>{{ t('controlRoom.resultReview', { id: fixture.id }) }}</strong><p>{{ t('controlRoom.resultReviewHint') }}</p></div>
        <Button size="small" :label="t('controlRoom.reviewResult')" severity="warn" outlined @click="emit('select', fixture.id)" />
      </article>
      <article v-for="player in waitingPlayers" :key="`waiting-${player.id}-${player.fixture_id}`" class="attention-item">
        <i class="bi bi-person-walking" aria-hidden="true"></i>
        <div>
          <strong><UserQuickView :user-id="player.user_id" :username="player.name" /></strong>
          <p>{{ t('controlRoom.waitingForOpponent', { round: player.round_name }) }}</p>
        </div>
        <Button size="small" :label="t('controlRoom.openMatch')" severity="secondary" text @click="emit('select', player.fixture_id)" />
      </article>
    </div>
  </section>
</template>

<style scoped>
.live-attention { margin-top: 16px; padding: 17px; border: 1px solid #664b30; border-radius: 14px; background: #201c20; }
.live-attention > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.live-attention header p { margin: 0 0 3px; color: #d9a95d; font-size: 10px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.live-attention h3 { margin: 0; color: #fff1dc; font-size: 16px; }
.live-attention header > span { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 999px; background: #713a31; color: #ffd1c2; font-size: 12px; font-weight: 800; }
.live-attention__items { display: grid; gap: 8px; }
.attention-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 11px; padding: 11px 12px; border: 1px solid #3b465b; border-radius: 10px; background: #172035; }
.attention-item > i { display: grid; width: 31px; height: 31px; place-items: center; border-radius: 8px; background: #263852; color: #9bc9f7; }
.attention-item strong { color: #edf4ff; font-size: 12px; }
.attention-item p { margin: 3px 0 0; color: #94a6bf; font-size: 10px; }
.attention-item--critical { border-color: #713e3b; }
.attention-item--critical > i { background: #4b2929; color: #ffaaa1; }
.attention-item--warning { border-color: #66522e; }
.attention-item--warning > i { background: #45391f; color: #f0ca6c; }
@media (max-width: 620px) { .attention-item { grid-template-columns: auto minmax(0, 1fr); } .attention-item :deep(.p-button) { grid-column: 2; width: fit-content; } }
</style>
