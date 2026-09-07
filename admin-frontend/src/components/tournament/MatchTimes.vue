<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { MatchAdministration } from '@/types/matchAdministration'
const props = defineProps<{ times: MatchAdministration['times'] }>()
const { t, locale } = useI18n()
const rows = computed(() => [
  { label: 'connection', value: props.times.connection_created_at },
  { label: 'observed', value: props.times.live_started_at },
  { label: 'ended', value: props.times.ended_at },
])
function date(value: string) {
  return new Date(value).toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-GB')
}
</script>
<template>
  <section class="match-times">
    <h3>{{ t('matchAdmin.times') }}</h3>
    <dl>
      <div v-for="row in rows" :key="row.label">
        <dt>{{ t(`matchAdmin.${row.label}`) }}</dt>
        <dd>{{ row.value ? date(row.value) : '—' }}</dd>
      </div>
    </dl>
    <small>{{ t('matchAdmin.timesHint') }}</small>
  </section>
</template>
<style scoped>
.match-times {
  padding: 16px;
  border: 1px solid #2b3e5e;
  border-radius: 12px;
  background: #142137;
}
h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}
dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  font-size: 12px;
}
dt,
small {
  color: #9fb3ce;
}
dd {
  margin: 5px 0 0;
  font-variant-numeric: tabular-nums;
}
small {
  display: block;
  margin-top: 10px;
  font-size: 11px;
}
@media (max-width: 500px) {
  dl {
    grid-template-columns: 1fr;
  }
}
</style>
