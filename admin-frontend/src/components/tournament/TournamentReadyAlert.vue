<script setup lang="ts">
import TournamentActionCard from './TournamentActionCard.vue'
import { useI18n } from '@/i18n'

defineProps<{
  participantCount: number
  minPlayers: number
  starting?: boolean
}>()
const emit = defineEmits<{ start: [] }>()

const { t } = useI18n()
</script>

<template>
  <section
    class="tournament-ready-alert"
    role="status"
    aria-live="polite"
    :aria-label="t('tournamentActions.ready')"
  >
    <div class="tournament-ready-alert__message">
      <span class="tournament-ready-alert__icon" aria-hidden="true">
        <i class="bi bi-bell-fill"></i>
      </span>
      <div class="min-w-0">
        <p class="tournament-ready-alert__eyebrow">{{ t('tournamentActions.minimumReached') }}</p>
        <h2>{{ t('tournamentActions.ready') }}</h2>
        <p>{{ t('tournamentActions.readyHint') }}</p>
        <span class="tournament-ready-alert__count" dir="auto">
          {{ participantCount }} {{ t('tournamentActions.minimum', { count: minPlayers }) }}
        </span>
      </div>
    </div>

    <TournamentActionCard
      class="tournament-ready-alert__action"
      :label="t('tournamentActions.start')"
      :description="t('tournamentActions.startHint')"
      icon="bi bi-play-fill"
      tone="green"
      :loading="starting"
      @activate="emit('start')"
    />
  </section>
</template>

<style scoped>
.tournament-ready-alert {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(270px, 390px);
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
  padding: 18px;
  border: 1px solid #27745f;
  border-radius: 14px;
  background: linear-gradient(120deg, #12352f, #10283a);
  box-shadow: 0 12px 32px rgb(5 20 30 / 20%);
}
.tournament-ready-alert__message {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}
.tournament-ready-alert__icon {
  display: grid;
  flex: 0 0 42px;
  height: 42px;
  place-items: center;
  border-radius: 12px;
  background: #1a8068;
  color: #e1fff6;
  box-shadow: 0 0 0 5px rgb(82 218 179 / 9%);
}
.tournament-ready-alert__eyebrow {
  margin: 0 0 5px;
  color: #79dabd;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .07em;
  text-transform: uppercase;
}
.tournament-ready-alert h2 {
  margin: 0;
  color: #f0fff9;
  font-size: 18px;
  font-weight: 700;
}
.tournament-ready-alert__message > div > p:not(.tournament-ready-alert__eyebrow) {
  margin: 5px 0 0;
  color: #b7d9cf;
  font-size: 12px;
  line-height: 1.55;
}
.tournament-ready-alert__count {
  display: inline-flex;
  margin-top: 9px;
  border-radius: 999px;
  padding: 4px 9px;
  background: rgb(120 218 190 / 10%);
  color: #9ce7d1;
  font-size: 11px;
  font-weight: 650;
}
.tournament-ready-alert__action { margin: 0; }
@media (max-width: 760px) {
  .tournament-ready-alert { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 460px) {
  .tournament-ready-alert { padding: 14px; }
  .tournament-ready-alert__icon { flex-basis: 36px; height: 36px; }
}
</style>
