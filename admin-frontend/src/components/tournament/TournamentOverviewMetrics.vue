<script setup lang="ts">
import { useI18n } from '@/i18n'

export interface TournamentOverviewMetric {
  id: string
  label: string
  value: string
  hint: string
  icon: string
  tone?: 'neutral' | 'good' | 'warning'
}

defineProps<{ metrics: TournamentOverviewMetric[] }>()
const { t } = useI18n()
</script>

<template>
  <section class="overview-metrics" :aria-label="t('tournamentOverview.snapshot')">
    <article
      v-for="metric in metrics"
      :key="metric.id"
      class="overview-metric"
      :class="`overview-metric--${metric.tone ?? 'neutral'}`"
    >
      <span class="overview-metric__icon"><i :class="['bi', metric.icon]" aria-hidden="true"></i></span>
      <div class="overview-metric__copy">
        <p>{{ metric.label }}</p>
        <strong>{{ metric.value }}</strong>
        <span>{{ metric.hint }}</span>
      </div>
    </article>
  </section>
</template>

<style scoped>
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.overview-metric {
  display: flex;
  min-width: 0;
  gap: 12px;
  padding: 16px;
  border: 1px solid #2a3d5e;
  border-radius: 12px;
  background: #121d32;
}
.overview-metric__icon {
  display: grid;
  flex: 0 0 34px;
  height: 34px;
  place-items: center;
  border-radius: 9px;
  background: #213555;
  color: #90c9ff;
}
.overview-metric__copy { display: grid; min-width: 0; gap: 3px; }
.overview-metric p {
  overflow: hidden;
  margin: 0;
  color: #8da1be;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .05em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}
.overview-metric strong { color: #f3f7ff; font-size: 21px; font-weight: 700; line-height: 1.25; }
.overview-metric__copy > span { color: #aabbd3; font-size: 11px; line-height: 1.4; }
.overview-metric--good { border-color: #23624f; }
.overview-metric--good .overview-metric__icon { background: #153f37; color: #78e0bf; }
.overview-metric--warning { border-color: #72592c; }
.overview-metric--warning .overview-metric__icon { background: #463a24; color: #f1c86c; }
</style>
