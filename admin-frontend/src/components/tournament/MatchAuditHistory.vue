<script setup lang="ts">
import { useI18n } from '@/i18n'
import type { MatchAuditEvent, MatchAdminPlayer } from '@/types/matchAdministration'
defineProps<{ events: MatchAuditEvent[]; players: MatchAdminPlayer[]; expanded?: boolean }>()
const { t, locale } = useI18n()
function date(value: string) {
  return new Date(value).toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-GB')
}
function score(value?: Array<number | null>) {
  return value?.map((n) => n ?? '–').join(' : ') ?? '– : –'
}
</script>
<template>
  <details class="audit" :open="expanded">
    <summary>
      {{ t('matchAdmin.history') }} <span>{{ events.length }}</span>
    </summary>
    <p v-if="!events.length" class="muted">{{ t('matchAdmin.noHistory') }}</p>
    <ol v-else>
      <li v-for="event in events" :key="event.id">
        <div class="audit__heading">
          <strong>{{ t(`matchAdmin.actions.${event.action}`) }}</strong
          ><time :datetime="event.at">{{ date(event.at) }}</time>
        </div>
        <small>{{ event.actor || t('matchAdmin.system') }}</small>
        <p v-if="event.after.participant_id">
          {{
            players.find((p) => p.id === event.after.participant_id)?.name ||
            `#${event.after.participant_id}`
          }}
        </p>
        <p v-if="['score', 'game_result', 'player_result'].includes(event.action)" dir="ltr">
          {{ score(event.before.score) }} → {{ score(event.after.score) }}
        </p>
        <p v-if="event.reason" class="audit__reason">{{ event.reason }}</p>
        <p v-if="event.after.refund" class="audit__refund">
          {{
            t('matchAdmin.refunded', {
              amount: Number(event.after.refund.amount).toLocaleString(locale),
            })
          }}
        </p>
        <details v-if="event.action === 'note'" class="audit__note">
          <summary>{{ t('matchAdmin.noteChanges') }}</summary>
          <del>{{ event.before.note || '—' }}</del>
          <p>{{ event.after.note || '—' }}</p>
        </details>
      </li>
    </ol>
  </details>
</template>
<style scoped>
.audit {
  border: 1px solid #2b3e5e;
  border-radius: 12px;
  padding: 16px;
}
summary {
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
summary span {
  margin-inline-start: 6px;
  color: #8ad8f7;
}
ol {
  list-style: none;
  padding: 0;
  margin: 16px 0 0;
  max-height: 300px;
  overflow-y: auto;
}
li {
  border-inline-start: 2px solid #375575;
  padding: 0 12px 16px;
  margin-bottom: 8px;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.audit__heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 6px;
}
time,
small,
.muted {
  color: #a2b6cf;
  font-size: 11px;
}
p {
  margin-top: 6px;
  white-space: pre-wrap;
}
.audit__refund {
  color: #73e0be;
}
.audit__note {
  margin-top: 8px;
}
.audit__note summary {
  font-size: 12px;
}
del {
  display: block;
  color: #abb8ca;
  margin-top: 8px;
  white-space: pre-wrap;
}
</style>
