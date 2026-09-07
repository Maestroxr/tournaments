<script setup lang="ts">
import { computed } from 'vue'
import UserQuickView from './UserQuickView.vue'
import type { TournamentFixture, TournamentProgressPlayer } from '@/types/tournamentProgress'
import { useI18n } from '@/i18n'

const props = defineProps<{
  fixture: TournamentFixture
}>()
const emit = defineEmits<{ select: [id: number] }>()
const { t } = useI18n()

const hasResult = computed(() => props.fixture.score1 != null || props.fixture.score2 != null)

const resultState = computed(() => {
  if (props.fixture.is_confirmed) {
    const label = props.fixture.admin_resolution === 'disqualify' ? 'matchAdmin.disqualifiedStatus'
      : props.fixture.admin_resolution === 'advance' ? 'matchAdmin.advancedStatus' : 'tournaments.confirmed'
    return { key: 'confirmed', label: t(label), icon: 'bi-check-circle-fill' }
  }
  if (hasResult.value) {
    return {
      key: 'confirming',
      label: t('tournaments.awaitingConfirmation'),
      icon: 'bi-hourglass-split',
    }
  }
  if (props.fixture.operational_status === 'stalled') {
    return { key: 'stalled', label: t('controlRoom.stalled'), icon: 'bi-exclamation-octagon-fill' }
  }
  if (props.fixture.live?.status === 'playing') {
    return { key: 'playing', label: t('tournaments.inProgress'), icon: 'bi-play-circle-fill' }
  }
  if (props.fixture.operational_status === 'waiting_opponent') {
    return { key: 'waiting-opponent', label: t('controlRoom.waitingOpponent'), icon: 'bi-person-plus' }
  }
  if (props.fixture.operational_status === 'upcoming') {
    return { key: 'upcoming', label: t('controlRoom.upcoming'), icon: 'bi-calendar-event' }
  }
  return { key: 'waiting', label: t('tournaments.waiting'), icon: 'bi-clock' }
})

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return ''
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remaining = seconds % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`
    : `${minutes}:${String(remaining).padStart(2, '0')}`
}

const resultMessage = computed(() => {
  if (props.fixture.is_confirmed) return t('tournaments.resultLocked')
  if (hasResult.value) {
    return t('tournaments.confirmations', {
      count: props.fixture.confirmations,
      required: props.fixture.required_confirmations,
    })
  }
  return t('tournaments.scorePending')
})

function playerInitial(player: TournamentProgressPlayer | null) {
  return player?.name?.trim().charAt(0).toUpperCase() || '?'
}

function playerName(player: TournamentProgressPlayer | null) {
  return player?.name || t('tournaments.awaitingPlayer')
}

function isWinner(slot: 1 | 2) {
  const { fixture } = props
  if (fixture.is_confirmed && fixture.winner_id != null) return fixture.winner_id === (slot === 1 ? fixture.player1?.id : fixture.player2?.id)
  if (!fixture.is_confirmed || fixture.score1 == null || fixture.score2 == null) return false
  return slot === 1 ? fixture.score1 > fixture.score2 : fixture.score2 > fixture.score1
}
</script>

<template>
  <article :class="['fixture-card', `fixture-card--${resultState.key}`]">
    <header class="fixture-card__header">
      <p class="fixture-card__meta">
        <span>{{ t('tournaments.matchNumber', { id: fixture.id }) }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ t('tournaments.headToHead') }}</span>
      </p>
      <span class="fixture-card__status">
        <i :class="['bi', resultState.icon]" aria-hidden="true"></i>
        {{ resultState.label }}
      </span>
    </header>

    <div class="fixture-card__matchup">
      <section :class="['fixture-card__player', isWinner(1) && 'is-winner']">
        <span class="fixture-card__avatar" aria-hidden="true">{{
          playerInitial(fixture.player1)
        }}</span>
        <div class="fixture-card__identity">
          <span class="fixture-card__player-label">{{ t('tournaments.playerOne') }}</span>
          <UserQuickView
            class="fixture-card__user"
            :user-id="fixture.player1?.user_id ?? null"
            :username="playerName(fixture.player1)"
          />
          <span
            v-if="fixture.player1?.username && fixture.player1.username !== fixture.player1.name"
            class="fixture-card__username"
            dir="ltr"
            >@{{ fixture.player1.username }}</span
          >
        </div>
        <i
          v-if="isWinner(1)"
          class="bi bi-trophy-fill fixture-card__winner"
          :title="t('tournaments.winner')"
          aria-hidden="true"
        ></i>
        <strong class="fixture-card__player-score">{{ fixture.score1 ?? '–' }}</strong>
      </section>

      <div class="fixture-card__divider" aria-hidden="true">
        <span>{{ t('tournaments.versus') }}</span>
      </div>

      <section
        :class="[
          'fixture-card__player',
          'fixture-card__player--second',
          isWinner(2) && 'is-winner',
        ]"
      >
        <span class="fixture-card__avatar" aria-hidden="true">{{
          playerInitial(fixture.player2)
        }}</span>
        <div class="fixture-card__identity">
          <span class="fixture-card__player-label">{{ t('tournaments.playerTwo') }}</span>
          <UserQuickView
            class="fixture-card__user"
            :user-id="fixture.player2?.user_id ?? null"
            :username="playerName(fixture.player2)"
          />
          <span
            v-if="fixture.player2?.username && fixture.player2.username !== fixture.player2.name"
            class="fixture-card__username"
            dir="ltr"
            >@{{ fixture.player2.username }}</span
          >
        </div>
        <i
          v-if="isWinner(2)"
          class="bi bi-trophy-fill fixture-card__winner"
          :title="t('tournaments.winner')"
          aria-hidden="true"
        ></i>
        <strong class="fixture-card__player-score">{{ fixture.score2 ?? '–' }}</strong>
      </section>
    </div>

    <div class="fixture-card__summary">
      <span class="fixture-card__summary-copy">
        <i
          :class="[
            'bi',
            fixture.is_confirmed ? 'bi-lock-fill' : hasResult ? 'bi-people' : 'bi-info-circle',
          ]"
          aria-hidden="true"
        ></i>
        {{ resultMessage }}
      </span>
      <button
        v-if="fixture.editable && !fixture.is_confirmed"
        type="button"
        class="fixture-card__admin"
        @click="emit('select', fixture.id)"
      >
        <i class="bi bi-eye" aria-hidden="true"></i>
        {{ t('tournaments.adminAction') }}
        <i class="bi bi-chevron-right fixture-card__admin-arrow rtl:rotate-180" aria-hidden="true"></i>
      </button>
    </div>

    <div v-if="fixture.started_at" class="fixture-card__timing">
      <span><i class="bi bi-stopwatch" aria-hidden="true"></i>{{ t('controlRoom.elapsed') }}</span>
      <strong dir="ltr">{{ formatDuration(fixture.duration_seconds) }}</strong>
      <span v-if="fixture.stalled" class="fixture-card__stale"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i>{{ t('controlRoom.noRecentActivity') }}</span>
    </div>

    <dl v-if="fixture.live && !fixture.is_confirmed" class="fixture-card__live-stats">
      <div>
        <dt><i class="bi bi-broadcast" aria-hidden="true"></i>{{ t('tournaments.liveScore') }}</dt>
        <dd dir="ltr">
          {{ fixture.live.match_score.white }} : {{ fixture.live.match_score.black }}
        </dd>
      </div>
      <div>
        <dt><i class="bi bi-arrow-repeat" aria-hidden="true"></i>{{ t('tournaments.turn') }}</dt>
        <dd>{{ fixture.live.state.turn || t('tournaments.waiting') }}</dd>
      </div>
      <div>
        <dt><i class="bi bi-dice-6" aria-hidden="true"></i>{{ t('tournaments.cube') }}</dt>
        <dd>{{ fixture.live.state.cube || 1 }}</dd>
      </div>
    </dl>
  </article>
</template>

<style scoped>
.fixture-card {
  position: relative;
  align-self: start;
  overflow: hidden;
  padding: 16px;
  border: 1px solid rgba(116, 148, 197, 0.22);
  border-radius: 14px;
  background: linear-gradient(145deg, rgba(22, 35, 61, 0.98), rgba(14, 24, 43, 0.98));
  box-shadow: 0 12px 28px rgba(2, 8, 23, 0.18);
}
.fixture-card::before {
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: #526987;
  content: '';
}
.fixture-card--playing::before {
  background: #4ab6e4;
  box-shadow: 0 0 16px rgba(74, 182, 228, 0.6);
}
.fixture-card--confirming::before {
  background: #d9b65d;
}
.fixture-card--stalled { border-color: rgba(220, 91, 77, .55); }
.fixture-card--stalled::before { background: #e16b5b; box-shadow: 0 0 16px rgba(225, 107, 91, .5); }
.fixture-card--stalled .fixture-card__status { border-color: rgba(225, 107, 91, .5); background: rgba(116, 45, 40, .25); color: #ffb8ae; }
.fixture-card--waiting-opponent::before, .fixture-card--upcoming::before { background: #7586a1; }
.fixture-card--confirmed::before {
  background: #42b89b;
}
.fixture-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.fixture-card__meta {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #90a6c6;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.fixture-card__status {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  min-height: 27px;
  padding: 0 10px;
  border: 1px solid #3a4b69;
  border-radius: 999px;
  background: #17243d;
  color: #b6c5dc;
  font-size: 11px;
  font-weight: 650;
}
.fixture-card--playing .fixture-card__status {
  border-color: rgba(74, 182, 228, 0.45);
  background: rgba(31, 111, 150, 0.18);
  color: #79d9ff;
}
.fixture-card--confirming .fixture-card__status {
  border-color: rgba(217, 182, 93, 0.4);
  background: rgba(217, 182, 93, 0.12);
  color: #edd38d;
}
.fixture-card--confirmed .fixture-card__status {
  border-color: rgba(66, 184, 155, 0.4);
  background: rgba(66, 184, 155, 0.12);
  color: #8de1ca;
}
.fixture-card__matchup {
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid rgba(116, 148, 197, 0.18);
  border-radius: 11px;
  background: rgba(7, 14, 28, 0.4);
}
.fixture-card__player {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 9px 12px;
}
.fixture-card__player--second {
  text-align: start;
}
.fixture-card__player.is-winner {
  background: linear-gradient(90deg, rgba(42, 122, 101, 0.24), transparent 72%);
}
.fixture-card__avatar {
  display: grid;
  flex: 0 0 36px;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid rgba(126, 175, 255, 0.24);
  border-radius: 10px;
  background: linear-gradient(145deg, #29466f, #1a2d4e);
  color: #cfe0ff;
  font-size: 13px;
  font-weight: 750;
}
.fixture-card__identity {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
}
.fixture-card__player-label {
  color: #8191ac;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.fixture-card__username {
  max-width: 100%;
  overflow: hidden;
  color: #8495b1;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fixture-card__winner {
  flex: 0 0 auto;
  color: #79d5bd;
  font-size: 12px;
}
.fixture-card__player-score {
  flex: 0 0 36px;
  margin-inline-start: auto;
  color: #f4f7ff;
  font-size: 22px;
  line-height: 1;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.fixture-card:not(.fixture-card--confirmed):not(.fixture-card--confirming)
  .fixture-card__player-score {
  color: #64748f;
}
.fixture-card__user {
  max-width: 100%;
}
.fixture-card__user :deep(.p-button) {
  max-width: 100%;
  justify-content: flex-start;
  padding: 0 !important;
  color: #f2f6ff !important;
  font-size: 13px;
  line-height: 1.4;
  text-decoration: none !important;
}
.fixture-card__user :deep(.p-button-icon) {
  display: none;
}
.fixture-card__user :deep(.p-button-label) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fixture-card__user :deep(> .font-medium) {
  max-width: 100%;
  overflow: hidden;
  color: #f2f6ff !important;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fixture-card__divider {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 1px;
  margin-inline: 12px;
  background: rgba(116, 148, 197, 0.18);
}
.fixture-card__divider span {
  padding: 0 8px;
  background: #111c31;
  color: #7187a8;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.12em;
}
.fixture-card__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #263653;
  font-size: 11px;
}
.fixture-card__summary-copy {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #9dacc5;
}
.fixture-card__summary-copy i {
  color: #6f9cdb;
}
.fixture-card__admin {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid rgba(112, 170, 255, 0.32);
  border-radius: 8px;
  background: rgba(48, 112, 204, 0.14);
  color: #c7dcff;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    transform 0.16s ease;
}
.fixture-card__admin:hover {
  border-color: rgba(130, 187, 255, 0.62);
  background: rgba(48, 112, 204, 0.24);
  transform: translateY(-1px);
}
.fixture-card__admin:focus-visible {
  outline: 2px solid #75b6ff;
  outline-offset: 2px;
}
.fixture-card__admin i {
  color: #83b8ff;
}
.fixture-card__admin-arrow {
  font-size: 9px;
}
.fixture-card__live-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid #293a58;
  border-radius: 9px;
  background: #293a58;
}
.fixture-card__timing { display: flex; align-items: center; gap: 8px; margin-top: 11px; color: #879bb8; font-size: 10px; }
.fixture-card__timing > span:first-child { display: inline-flex; align-items: center; gap: 5px; }
.fixture-card__timing strong { color: #d7e7fa; font-size: 11px; font-variant-numeric: tabular-nums; }
.fixture-card__stale { display: inline-flex; align-items: center; gap: 5px; margin-inline-start: auto; color: #ff9f92; font-weight: 700; }
.fixture-card__live-stats > div {
  min-width: 0;
  padding: 9px 11px;
  background: #121e35;
}
.fixture-card__live-stats dt {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #8091ad;
  font-size: 9px;
  text-transform: uppercase;
}
.fixture-card__live-stats dt i {
  color: #64c9f3;
  font-size: 10px;
}
.fixture-card__live-stats dd {
  margin: 3px 0 0;
  overflow: hidden;
  color: #eaf1ff;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  text-transform: capitalize;
  white-space: nowrap;
}
@media (max-width: 560px) {
  .fixture-card {
    padding: 15px;
  }
  .fixture-card__meta span:last-child,
  .fixture-card__meta span[aria-hidden='true'] {
    display: none;
  }
  .fixture-card__summary {
    align-items: flex-start;
    flex-direction: column;
  }
  .fixture-card__admin {
    width: 100%;
    justify-content: center;
  }
}
</style>
