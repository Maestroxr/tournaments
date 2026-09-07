<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { TournamentFixture } from '@/types/tournamentProgress'

const props = defineProps<{
  fixture: TournamentFixture
  connected?: boolean
  updatedAt?: Date | null
}>()
const { t, locale } = useI18n()
const live = computed(() => (props.fixture.is_confirmed ? null : props.fixture.live))
const turn = computed(() => {
  const value = live.value?.state?.turn
  return value === 'white' || value === 'black' ? t(`matchDetails.${value}`) : '—'
})
const updated = computed(() =>
  props.updatedAt?.toLocaleTimeString(locale.value === 'he' ? 'he-IL' : 'en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }),
)
</script>

<template>
  <section
    v-if="!fixture.is_confirmed"
    class="match-live"
    :aria-label="t('matchDetails.liveTitle')"
  >
    <header>
      <h3><i class="bi bi-broadcast" aria-hidden="true"></i> {{ t('matchDetails.liveTitle') }}</h3>
      <span :class="['match-live__connection', connected && 'is-connected']">
        <i aria-hidden="true"></i
        >{{ t(connected ? 'matchDetails.connected' : 'matchDetails.periodic') }}
      </span>
    </header>
    <template v-if="live">
      <div class="match-live__score" aria-live="polite" aria-atomic="true">
        <h4>{{ t('matchDetails.liveScore') }}</h4>
        <p dir="ltr">{{ live.match_score.white }} : {{ live.match_score.black }}</p>
      </div>
      <dl>
        <div>
          <dt>{{ t('matchDetails.turn') }}</dt>
          <dd>{{ turn }}</dd>
        </div>
        <div>
          <dt>{{ t('matchDetails.dice') }}</dt>
          <dd dir="ltr">{{ live.state?.dice?.length ? live.state.dice.join(' · ') : '—' }}</dd>
        </div>
        <div>
          <dt>{{ t('matchDetails.cube') }}</dt>
          <dd>{{ live.state?.cube ?? '—' }}</dd>
        </div>
      </dl>
      <small>{{ t('matchDetails.liveHint') }}</small>
    </template>
    <p v-else class="match-live__empty">{{ t('matchDetails.noLive') }}</p>
    <small v-if="updated" class="match-live__updated">{{
      t('matchDetails.lastSync', { time: updated })
    }}</small>
  </section>
</template>

<style scoped>
.match-live {
  margin-top: 18px;
  padding: 16px;
  border: 1px solid #245566;
  border-radius: 12px;
  background: linear-gradient(135deg, #10303b, #132538);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
h3 {
  color: #98e5f1;
  font-size: 14px;
  font-weight: 650;
}
.match-live__connection {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #bdc8da;
  font-size: 11px;
}
.match-live__connection i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.match-live__connection.is-connected {
  color: #86e8c5;
}
.match-live__score {
  text-align: center;
  padding: 18px 0;
}
h4 {
  color: #accbd7;
  font-size: 12px;
  font-weight: 400;
}
.match-live__score p {
  margin-top: 4px;
  color: #f0fbff;
  font-size: 34px;
  line-height: 1.3;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
dl > div {
  background: #07152350;
  border: 1px solid #2a4559;
  border-radius: 8px;
  padding: 10px;
  text-align: center;
}
dt {
  color: #a5bdce;
  font-size: 11px;
}
dd {
  margin: 5px 0 0;
  color: #edf6ff;
  font-size: 15px;
  font-weight: 600;
}
small,
.match-live__empty {
  color: #a8c3d3;
  font-size: 12px;
  line-height: 1.6;
}
.match-live__empty {
  margin: 14px 0 0;
}
.match-live__updated {
  display: block;
  margin-top: 10px;
  font-size: 11px;
}
</style>
