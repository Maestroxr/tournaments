<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { TournamentFixture } from '@/types/tournamentProgress'
import type { MatchIncidentAction } from '@/types/matchAdministration'
import { isStatusEvent } from '@/services/tournamentStatusEvents'
import { isMatchSettled, needsMatchAdjudication } from '@/services/matchAdjudication'
import MatchAdjudicationNotice from './MatchAdjudicationNotice.vue'

const props = defineProps<{
  fixture: TournamentFixture
  connected?: boolean
  updatedAt?: Date | null
  settled?: boolean
  canRule?: boolean
  disabled?: boolean
  showActions?: boolean
}>()
const emit = defineEmits<{ action: [value: MatchIncidentAction] }>()
const { t, locale } = useI18n()
const closed = computed(() => props.settled || isMatchSettled(props.fixture))
const live = computed(() => (closed.value ? null : props.fixture.live))
const needsDecision = computed(() => !closed.value && needsMatchAdjudication(props.fixture))
const statusOnly = computed(() => isStatusEvent(live.value))
const title = computed(() =>
  t(
    statusOnly.value || needsDecision.value ? 'matchDetails.statusTitle' : 'matchDetails.liveTitle',
  ),
)
const turn = computed(() => {
  const value = live.value?.state?.turn
  return value === 'white' || value === 'black' ? t('matchDetails.' + value) : '—'
})
const updated = computed(() => {
  const value = props.updatedAt
  return value && Number.isFinite(value.getTime())
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(
        value,
      )
    : null
})
</script>

<template>
  <section
    v-if="!closed"
    :class="[
      'match-live mt-[18px] rounded-xl border p-4',
      needsDecision
        ? 'border-amber-500/50 bg-[#201b10] text-amber-50'
        : 'border-[#245566] bg-[#132b36] text-[#edf6ff]',
    ]"
    :aria-label="title"
  >
    <header class="flex flex-wrap items-center justify-between gap-2.5">
      <h3 :class="['text-sm font-semibold', needsDecision ? 'text-amber-200' : 'text-[#98e5f1]']">
        <i class="bi bi-broadcast" aria-hidden="true"></i> {{ title }}
      </h3>
      <span
        :class="[
          'match-live__connection inline-flex items-center gap-1.5 text-xs',
          connected ? 'text-emerald-200' : 'text-slate-200',
        ]"
      >
        <i class="size-1.5 rounded-full bg-current" aria-hidden="true"></i>
        {{ t(connected ? 'matchDetails.connected' : 'matchDetails.periodic') }}
      </span>
    </header>
    <MatchAdjudicationNotice
      v-if="needsDecision"
      :absent-since="live?.state.presence?.absentSince"
      :occurred-at="live?.event_type === 'admin_required' ? live.occurred_at : null"
      :can-rule="canRule"
      :disabled="disabled"
      :show-actions="showActions"
      @action="emit('action', $event)"
    />
    <p v-else-if="statusOnly" class="mt-3 text-sm text-slate-100" role="status">
      {{ t('matchDetails.statusPlaying') }}
    </p>
    <template v-else-if="live">
      <div class="match-live__score py-[18px] text-center" aria-live="polite" aria-atomic="true">
        <h4 class="text-xs font-normal text-[#accbd7]">{{ t('matchDetails.liveScore') }}</h4>
        <p class="mt-1 text-[34px] leading-snug font-bold text-[#f0fbff] tabular-nums" dir="ltr">
          {{ live.match_score.white }} : {{ live.match_score.black }}
        </p>
      </div>
      <dl class="mb-3 grid grid-cols-3 gap-2">
        <div class="rounded-lg border border-[#2a4559] bg-[#07152350] p-2.5 text-center">
          <dt class="text-xs text-[#a5bdce]">{{ t('matchDetails.turn') }}</dt>
          <dd class="mt-1 text-[15px] font-semibold">{{ turn }}</dd>
        </div>
        <div class="rounded-lg border border-[#2a4559] bg-[#07152350] p-2.5 text-center">
          <dt class="text-xs text-[#a5bdce]">{{ t('matchDetails.dice') }}</dt>
          <dd class="mt-1 text-[15px] font-semibold" dir="ltr">
            {{ live.state?.dice?.length ? live.state.dice.join(' · ') : '—' }}
          </dd>
        </div>
        <div class="rounded-lg border border-[#2a4559] bg-[#07152350] p-2.5 text-center">
          <dt class="text-xs text-[#a5bdce]">{{ t('matchDetails.cube') }}</dt>
          <dd class="mt-1 text-[15px] font-semibold">{{ live.state?.cube ?? '—' }}</dd>
        </div>
      </dl>
      <small class="text-xs leading-relaxed text-[#a8c3d3]">{{ t('matchDetails.liveHint') }}</small>
    </template>
    <p v-else class="match-live__empty mt-3.5 text-xs leading-relaxed text-[#a8c3d3]">
      {{ t('matchDetails.noLive') }}
    </p>
    <p class="mt-3 text-xs leading-relaxed text-slate-200">
      {{ t('matchDetails.feedExplanation') }}
    </p>
    <small class="match-live__updated mt-2.5 block text-xs text-slate-200">{{
      updated
        ? t('matchDetails.lastSync', { time: updated })
        : t('matchAdmin.incident.syncNotRecorded')
    }}</small>
  </section>
</template>
